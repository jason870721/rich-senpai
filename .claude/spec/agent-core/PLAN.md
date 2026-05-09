# Agent Core — Implementation Plan

Phased, end-to-end runnable at every milestone. Each phase finishes with a smoke test that proves the agent is alive at that level.

<br>

---

<br>

## Phase 0 — Skeleton & smoke test  *(half-day)*

**Goal**: prove we can call Claude with the existing tools and get a tool-use response back.

- [ ] Add `python-dotenv` and `tiktoken` to `requirements.txt`. Keep `anthropic`, `requests` pins.
- [ ] Implement `core/agent_core.py` with a minimal `AgentCore.run_cycle(market_state)` that:
  - builds one user message from `market_state`,
  - calls `client.messages.create` with `tool_register.TOOL_SPECS`,
  - prints the response, dispatches **one** tool call if present, prints the tool result, returns.
- [ ] Hard-code `system_prompt` to a 3-line trimmed version of the README prompt for now.
- [ ] Replace `main.py` body with `AgentCore(...).run_cycle("BTC=68000, no positions")`.

**Done when**: `python main.py` exits 0, prints an assistant message, and (likely) one tool roundtrip.

<br>

## Phase 1 — Full ReAct loop  *(1 day)*

**Goal**: the loop iterates until the model stops asking for tools.

- [ ] Replace the single-shot dispatch with the loop in `SPEC.md §4`.
- [ ] Honor `stop_reason == "tool_use"` vs anything else.
- [ ] Sequentially execute every `tool_use` block in a response, batch all `tool_result`s into the next user turn.
- [ ] Add `max_iterations` cap with a clear `CycleResult(stop_reason="max_iterations")` exit.
- [ ] Register a synthetic `wait` tool spec (no-op handler) and intercept it in the core to exit cleanly with `stop_reason="wait"`.

**Done when**: a contrived prompt that forces 3+ tool turns runs end-to-end and terminates on `wait`.

<br>

## Phase 2 — Short memory plumbing  *(half-day)*

**Goal**: the agent has a persistent scratchpad across cycles.

- [ ] Add `tools/update_short_memory.py` (writes the file). Wire into `tool_register`.
- [ ] In `run_cycle`, read `short_memory.md` (create empty if missing) and inject it into the user message as a fenced section.
- [ ] Add `tiktoken` token count of the file. If > 3000, prepend a one-line note to the user message: *"Your short memory is over budget — summarize it this cycle before doing anything else."*
- [ ] Smoke test: run two cycles in a row, observe that the second cycle sees what the first wrote.

**Done when**: two-cycle smoke test shows continuity through the file alone (no in-process state).

<br>

## Phase 3 — Audit logging  *(half-day)*

**Goal**: every cycle writes a row to `agent_logs`, even if the agent crashes mid-cycle.

- [ ] Add `core/audit.py` with `init_db(path)` and `log_cycle(conn, CycleResult, raw_messages, market_state)`.
- [ ] `AgentCore.__init__` opens the sqlite connection and ensures the table exists.
- [ ] Wrap `run_cycle` body in try/finally so even an exception still produces an `agent_logs` row with `stop_reason="error"` and the traceback in `raw_messages`.
- [ ] Manual check: `sqlite3 rich_senpai.db 'select * from agent_logs;'`.

**Done when**: forced exception in a tool handler still produces a complete audit row.

<br>

## Phase 4 — System prompt & config polish  *(half-day)*

**Goal**: the runtime is configurable, the system prompt matches README §3.

- [ ] Move the full README system prompt into `core/system_prompt.py` (constant). Make sure the **Available Tools** section is generated from `TOOL_SPECS` so it never drifts.
- [ ] Read all config from env vars per `SPEC.md §7`. Fail fast with a clear error if `ANTHROPIC_API_KEY` is missing.
- [ ] Add `core/__init__.py` exporting `AgentCore`, `CycleResult`.
- [ ] Update `tools/README.md` with a one-line pointer to `.claude/spec/agent-core/`.

**Done when**: `from core import AgentCore` works, env vars override defaults, and the system prompt's tool list reflects whatever is registered.

<br>

## Phase 5 — Robustness  *(1 day)*

**Goal**: survive transient API errors and weird model output without dying.

- [ ] Wrap `client.messages.create` in a retry helper (3 attempts, exponential backoff, only retry on `anthropic.APIConnectionError` / `RateLimitError` / `InternalServerError`).
- [ ] Defensive parsing: if a `tool_use` block has malformed `input`, return `"error: invalid arguments: <repr>"` to the model rather than raising.
- [ ] Detect and break on **tool-loop oscillation**: if the same `(tool_name, input_hash)` is called 3 times in a row, return `stop_reason="tool_loop"` and surface in `agent_logs`.
- [ ] Add a hard wall-clock budget per cycle (default 5 min). Exceeding it → `stop_reason="timeout"`.

**Done when**: chaos test (mock LLM returning bad JSON / repeated tool calls / 500s) terminates cleanly with a useful `stop_reason`.

<br>

## Phase 6 — Tests  *(1 day)*

**Goal**: a small but real test suite so refactors don't regress the loop.

- [ ] `tests/test_agent_core.py` using a fake `Anthropic` client (a tiny class with `messages.create` returning canned `Message` objects).
- [ ] Cover: terminal `wait`, max_iterations exit, tool roundtrip, malformed tool input, retry path.
- [ ] Add `pytest` to requirements; document `pytest -q` in tools/README or a new top-level `CONTRIBUTING.md`.

**Done when**: `pytest -q` is green and CI-runnable.

<br>

---

<br>

## Out-of-phase / parallel work other modules will need

These are not the agent-core team's problem but unblock subsequent phases. Track in their own specs once those modules exist.

- `tools/db_query.py` (sqlite) — needed before the agent's own logging works.
- `tools/exec_py.py` — for the agent to compute indicators.
- `tools/explore_web.py` — DuckDuckGo or a simple scraper.
- `tools/exchange.py` — CCXT-backed `query_balance`, `query_positions`, `place_order`, `cancel_order`. Testnet-only.
- `scheduler.py` / `main.py` redesign — cron-style 5-minute tick driver.

<br>

## Sequencing

```
Phase 0 → 1 → 2 → 3 → 4 → 5 → 6
                   │
                   └─ unblocks parallel tool/db work
```

Phases 0–3 are the critical path to a runnable agent on `feature/agent-core`. 4–6 harden it before merging to `main`.
