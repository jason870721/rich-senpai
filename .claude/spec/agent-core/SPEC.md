# Agent Core — Specification

> Module: `core/agent_core.py`
> Owner area in repo: `core/`
> Branch of work: `feature/agent-core`

<br>

---

<br>

## 1. Purpose

The agent core is the **heartbeat of rich-senpai**. It is the ReAct loop that:

1. Assembles the prompt (system prompt + short memory + conversation history + new market state).
2. Calls the LLM (Anthropic Messages API; LiteLLM-compatible swap is a future option).
3. Parses any `tool_use` blocks the model emits, dispatches them through `tools.tool_register.call_tool`, and feeds the `tool_result` back into the next turn.
4. Loops until the model emits a terminal signal (`wait` / `done`) or a safety limit is hit.
5. Logs every step to the `agent_logs` table (once the DB layer exists) so we can audit what the agent did and why.

The core does **not**:

- Implement individual tools — those live under `tools/`.
- Schedule cycles — the outer cron / `main.py` runner does that. The core runs **one cycle** per call.
- Make trading decisions — the LLM does. The core only carries messages, calls tools, enforces limits.

<br>

## 2. Boundaries & dependencies

```
                          ┌────────────────────────┐
                          │      main.py / cron    │   one tick = 5 min
                          └───────────┬────────────┘
                                      │ run_cycle(market_state)
                                      ▼
        ┌─────────────────────────────────────────────────────────┐
        │                       agent_core                        │
        │   ┌────────────┐   ┌─────────────┐   ┌───────────────┐  │
        │   │ prompt     │ → │  llm client │ → │ tool dispatch │  │
        │   │ assembler  │   │  (Anthropic)│   │(tool_register)│  │
        │   └────────────┘   └─────────────┘   └───────────────┘  │
        │           ▲                ▲                  │         │
        │           │                │                  ▼         │
        │   short_memory.md     conversation     tools/<*>.py     │
        │                          history                        │
        └─────────────────────────────────────────────────────────┘
                                      │
                                      ▼
                              agent_logs (DB)
```

**Inbound dependencies**: `tools.tool_register` (already exists), `anthropic` SDK (already pinned).
**Outbound consumers**: `main.py`, eventually a `scheduler.py` and a UI/monitoring layer.

<br>

## 3. Public interface (target)

```python
# core/agent_core.py

@dataclass
class CycleResult:
    final_text: str            # last assistant text block
    stop_reason: str           # "wait" | "done" | "max_iterations" | "error"
    iterations: int
    tool_calls: list[ToolCall] # for logging / replay
    usage: dict                # token usage from the API


class AgentCore:
    def __init__(
        self,
        *,
        model: str = "claude-opus-4-7",
        system_prompt: str,
        short_memory_path: str = "short_memory.md",
        max_iterations: int = 25,
        max_tokens_per_call: int = 4096,
        client: anthropic.Anthropic | None = None,
    ): ...

    def run_cycle(self, market_state: str) -> CycleResult:
        """Run exactly one ReAct cycle and return when the model emits a
        terminal signal or max_iterations is hit. Mutates short_memory.md
        through the update_short_memory tool. Does NOT sleep between
        cycles — the caller schedules that."""
```

A bare-minimum CLI entry point exists in `main.py` for local smoke tests, but the supported interface is `AgentCore.run_cycle`.

<br>

## 4. ReAct loop semantics

One **cycle** = one call to `run_cycle`. Inside a cycle, we may iterate up to `max_iterations` LLM turns:

```
messages = []                            # user/assistant turns this cycle
messages.append(user(market_state + short_memory_block))

for i in range(max_iterations):
    resp = client.messages.create(
        model=..., system=system_prompt, tools=TOOL_SPECS, messages=messages,
        max_tokens=max_tokens_per_call,
    )
    messages.append(assistant(resp.content))

    if resp.stop_reason != "tool_use":
        return CycleResult(stop_reason="done", ...)

    tool_results = []
    for block in resp.content:
        if block.type == "tool_use":
            if block.name == "wait":
                return CycleResult(stop_reason="wait", ...)
            output = tool_register.call_tool(block.name, block.input)
            tool_results.append(tool_result_block(block.id, output))

    messages.append(user(tool_results))

return CycleResult(stop_reason="max_iterations", ...)
```

Notes:

- **Single-source of tools**: the core uses `TOOL_SPECS` and `call_tool` — it has zero knowledge of which tools exist. New tools land by editing `tools/tool_register.py`.
- **`wait` is a synthetic tool**: it is registered as a no-op tool spec so the model can call it like any other tool. The core intercepts it before dispatch.
- **Error handling**: every tool already returns a string. If a tool raises, `call_tool` catches it. The core only adds a top-level try/except around `messages.create` for retryable network errors.

<br>

## 5. Memory model

### 5.1 Short-term memory (per-cycle injection)

- File: `short_memory.md` (project root, ignored only if user adds it).
- Read at the **start** of every cycle, formatted as:
  ```
  # SHORT MEMORY (your scratchpad from the last cycle)
  <contents>
  ```
- Concatenated into the **first user message** of the cycle alongside `market_state`.
- The agent updates it through the `update_short_memory` tool (overwrites the whole file).
- Token-budget guard: if the file exceeds 3000 tokens (counted with `tiktoken` cl100k or anthropic counter), prepend a system-warning user note instructing the agent to summarize. We do **not** truncate it ourselves — that loses information silently.

### 5.2 Long-term memory (DB)

- The agent owns its schema via `db_query`. The core does not touch it directly.
- The core writes a **mirrored audit row** to `agent_logs` after each cycle, regardless of whether the agent logged anything itself. Schema (created lazily by the core on first run):
  ```sql
  CREATE TABLE IF NOT EXISTS agent_logs (
      id            INTEGER PRIMARY KEY AUTOINCREMENT,
      cycle_started TIMESTAMP NOT NULL,
      cycle_ended   TIMESTAMP NOT NULL,
      stop_reason   TEXT NOT NULL,
      iterations    INTEGER NOT NULL,
      market_state  TEXT,
      raw_messages  TEXT,        -- JSON dump of the full message list
      tool_calls    TEXT,        -- JSON list [{name, input, output}]
      usage_in      INTEGER,
      usage_out     INTEGER
  );
  ```
- This table is the **forensic log**. The agent's own tables are its working memory.

### 5.3 Conversation history across cycles

- The core does **not** carry conversation history across cycles. Each cycle is a fresh `messages=[]`. Persistence between cycles flows through `short_memory.md` and the database — exactly as the README prescribes. This is intentional: a persistent chat history would grow unbounded and produce inconsistent behavior across restarts.

<br>

## 6. Safety & guardrails

The core enforces only **process-level** guardrails. Trading rules (5%-of-balance, stop-losses, etc.) are the LLM's job, anchored by the system prompt.

| Guardrail | Where enforced |
|---|---|
| `max_iterations` per cycle | core loop |
| `max_tokens_per_call` | LLM call args |
| Tool execution timeout | each tool (already in `bash.py`) |
| Tool-call audit log | core, post-cycle |
| Network retry with backoff | `_call_llm` helper, max 3 attempts |
| Prompt-size sanity check | warn (not block) if assembled prompt > 100k tokens |

Out-of-scope for the core (handled elsewhere): Docker isolation, testnet enforcement, balance gating.

<br>

## 7. Configuration

Read from environment variables, with sensible defaults:

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | required | LLM auth |
| `RICH_SENPAI_MODEL` | `claude-opus-4-7` | model id |
| `RICH_SENPAI_MAX_ITER` | `25` | safety cap |
| `RICH_SENPAI_MAX_TOKENS` | `4096` | per-call output cap |
| `RICH_SENPAI_DB_PATH` | `rich_senpai.db` | sqlite path for agent_logs |
| `RICH_SENPAI_SHORT_MEM` | `short_memory.md` | scratchpad path |

No `.env` parsing in the core itself — the runner (`main.py`) is responsible for loading it.

<br>

## 8. Open questions / non-goals

- **LiteLLM swap**: README mentions LiteLLM but the current SDK pin is `anthropic`. We'll keep the LLM call behind a single `_call_llm` method so swapping is a one-file change. Not building the abstraction up-front.
- **Streaming**: not in MVP. Cycles are short-lived; we want the full response before dispatching tools.
- **Parallel tool calls**: Anthropic supports them. We will execute sequentially in MVP — trading tools must be ordered (cancel before place, etc.) and parallelism adds race conditions we don't need yet.
- **Multi-agent / sub-agents**: explicitly out of scope. One agent, one loop.
