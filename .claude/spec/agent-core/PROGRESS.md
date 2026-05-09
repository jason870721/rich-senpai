# Agent Core — Progress

> Update this at the end of every working session. Keep it short — link to commits, not paragraphs.

<br>

## Current phase

**Phase 4 — System prompt & config polish** *(partial; constructor refactor deferred per user)*

The library-level deliverables landed: `core/system_prompt.py` with auto-generated `Available Tools` list, `core/__init__.py` exporting `AgentCore`/`CycleResult`/`ToolCall`, and the spec pointer in `tools/README.md`. The constructor-side env-var/fail-fast refactor was reverted twice by the user — `AgentCore.__init__` keeps literal-default parameters (`model=MODEL_NAME`, `system_prompt=SYSTEM_PROMPT_PHASE0`). The new `build_system_prompt()` is available as a library but is **not** wired in as the AgentCore default. See "Open questions" for the unresolved Phase 4 acceptance criterion.

<br>

## Done

- Tools layer (`tools/`): `read_file`, `write_file`, `bash`, `http_request`, plus `tool_register` with `SYS_TOOL_PROMPT`, `TOOL_SPECS`, `TOOL_HANDLERS`, `call_tool`. — commit `eec2c3f`
- Spec scaffolding under `.claude/spec/agent-core/` (this folder).
- **Phase 0 implementation:**
  - `requirements.txt` adds `python-dotenv >= 1.0.0` and `tiktoken >= 0.7.0`.
  - `core/agent_core.py`: `AgentCore` class + `CycleResult` / `ToolCall` dataclasses. `run_cycle` does one LLM call, dispatches every `tool_use` block once, prints text + tool I/O, returns a populated `CycleResult` with usage stats. `SYSTEM_PROMPT_PHASE0` is a 3-line trimmed prompt.
  - `main.py`: loads `.env`, instantiates `AgentCore()`, calls `run_cycle("BTC=68000, no positions")`, prints the stop_reason + usage.
  - Smoke verified: `from core.agent_core import AgentCore` resolves, all four tools register, `main.py` byte-compiles.
- **Phase 1 implementation:**
  - `tools/wait.py`: synthetic `wait` tool (no-op handler that errors if reached — the core intercepts the name before dispatch). `SPEC` has empty input schema.
  - `tools/tool_register.py`: `wait` added to `TOOL_SPECS` and `TOOL_HANDLERS`; `SYS_TOOL_PROMPT` updated to mention it.
  - `core/agent_core.py`: single-shot dispatch replaced with `for i in range(max_iterations)` loop. Per `SPEC.md §4`: appends assistant content, exits on `stop_reason != "tool_use"`, batches all `tool_result`s into one user turn, intercepts `wait` before `call_tool`, sums token usage across iterations. New `_result` helper centralizes the dataclass build.
  - System prompt bumped to mention `wait` so the model has a clean exit.
  - **Fake-client smoke**: 4 scenarios pass — (A) tool roundtrip then `end_turn`, (B) `wait` intercepted on first turn, (C) `max_iterations=3` cap hit on a tool-loop, (D) immediate `end_turn` with no tools.
- **Phase 2 implementation:**
  - `tools/update_short_memory.py`: SPEC takes `markdown_content`, handler overwrites the file. Path is read from `RICH_SENPAI_SHORT_MEM` at call time (default `short_memory.md`).
  - `tools/tool_register.py`: `update_short_memory` added to specs/handlers; `SYS_TOOL_PROMPT` updated.
  - `core/agent_core.py`:
    - New `_TIKTOKEN_ENCODER` (cl100k_base) + `_count_tokens` helper.
    - `AgentCore.__init__` accepts `short_memory_path` (env-var fallback) and `short_memory_token_budget` (default 3000).
    - `_read_short_memory` is side-effect-free: missing file → empty string.
    - `_build_initial_user_message` composes the first user turn: optional `[BUDGET WARNING]` line + `# SHORT MEMORY` section + `# MARKET STATE` section.
    - System prompt mentions `update_short_memory` and the 3000-token budget rule.
  - **Fake-client smoke**: 4 scenarios pass — (1) empty memory + tool writes thesis, (2) cycle 2 sees cycle 1's thesis through the file alone (no in-process state), (3) 5000-token file triggers `[BUDGET WARNING] ... over the 3000 budget`, (4) missing file → `(empty — first cycle)` marker, file is **not** auto-created.
- **Phase 3 implementation:**
  - `core/audit.py`: new module. `init_db(path)` opens a sqlite connection in autocommit mode and ensures the `agent_logs` table exists per `SPEC.md §5.2`. `log_cycle(...)` inserts one row, JSON-serializing `raw_messages` (Anthropic content blocks via `model_dump`, tool_result dicts pass through, strings pass through) and `tool_calls`. The traceback (when present) is written into the JSON envelope as `raw_messages.error`.
  - `core/agent_core.py`:
    - Imports `core.audit`, `datetime`, `traceback`.
    - `AgentCore.__init__` accepts `db_path` (env-var `RICH_SENPAI_DB_PATH` fallback, default `rich_senpai.db`), opens the connection, ensures schema. `close()` method added for explicit shutdown.
    - `run_cycle` body rewritten as `try / except BaseException / finally`:
      - All accumulator locals (`messages`, `tool_calls`, `final_text_parts`, totals, `iterations_attempted`) live before the `try` so the `finally` block can read partial state on exceptions.
      - Each early `return` first assigns to `result` so the `finally` block can log the same value the caller receives.
      - `except BaseException` captures the traceback for the audit row and re-raises (no suppression — covers `KeyboardInterrupt`/`SystemExit` too).
      - The `finally` block synthesizes a `CycleResult(stop_reason="error", ...)` if `result` is `None`, then calls `audit.log_cycle`. Audit failures are caught and printed so a misbehaving log can never mask the real cycle outcome.
  - `.gitignore`: added `rich_senpai.db` and `short_memory.md` to keep runtime state out of commits.
  - **Fake-client smoke**: 2 scenarios + manual sqlite read-back pass.
    - Normal cycle (`tool_use → wait`): row has `stop_reason="wait"`, `iterations=2`, `usage_in=24`/`usage_out=14`, `tool_calls` JSON contains the dispatched `read_file` (the synthetic `wait` is correctly excluded), `raw_messages.error` is `null`.
    - Mid-cycle `RuntimeError`: row still inserted with `stop_reason="error"`, `iterations=2`, partial tool_calls preserved, `raw_messages.error` contains the full traceback ending in `RuntimeError: simulated API outage`. Exception still propagates to the caller.
- **Micro-compaction (per-iteration tool_result trimming):**
  - `core/agent_core.py`: new module-level helper `_micro_compact_tool_results(messages, *, keep_recent=1, threshold=200)` that walks the message list, finds user turns containing `tool_result` blocks, and replaces the `content` of older blocks with `"[compacted: N chars elided]"` while preserving `tool_use_id` so the model can still match results to calls. Idempotent (already-short stubs pass through). Called once per iteration at the top of the loop, just before `client.messages.create`. Default policy: keep the most recent tool-result-bearing user turn intact, compact all earlier ones above 200 chars.
  - **Helper smoke**: 6 scenarios pass — (A) 3 tool_results with `keep_recent=1` → first 2 compacted, third intact, ids preserved; (B) idempotent on a second pass; (C) single tool_result not touched; (D) short older content under threshold passes through; (E) `keep_recent=0` compacts everything; (F) multiple tool_result blocks in one user turn all compacted, all ids preserved.
- **Phase 4 implementation (partial):**
  - `core/system_prompt.py`: new module. `build_system_prompt(tool_specs=None)` returns the README §3 prompt with the **Available Tools** section auto-rendered from `TOOL_SPECS` (JSON-schema → `(name: type, [optional: type])` signature, first sentence of description). README's JSON-block tool-call instruction was replaced with a paragraph about the native Anthropic tool_use protocol. Uses lazy import of `tools.tool_register` to avoid circulars.
  - `core/__init__.py`: exports `AgentCore`, `CycleResult`, `ToolCall`. `from core import AgentCore` now works.
  - `tools/README.md`: footer pointer to `.claude/spec/agent-core/`.
  - **Verified**: top-level import works; `build_system_prompt()` produces a 2828-char prompt with all 6 registered tools in the bullet list (`wait` correctly renders as `()`, optional params bracketed).
  - **Deferred (reverted by user, twice)**: `AgentCore.__init__` still uses literal defaults (`model=MODEL_NAME`, `system_prompt=SYSTEM_PROMPT_PHASE0`) rather than the env-var fallbacks specified in `SPEC.md §7`. Fail-fast on missing `ANTHROPIC_API_KEY` is **not** wired in. `build_system_prompt()` is available but **not** the constructor default.

<br>

## In flight

- Phase 0/1/2/3 final acceptance: end-to-end `python main.py` against a real API key. Needs user-side `.env` with `ANTHROPIC_API_KEY=...`. Expected on first run: empty short memory injected, ≥1 tool round-trip, terminates on `wait` or `end_turn`, exactly one row inserted into `rich_senpai.db::agent_logs`. Second invocation should see the persisted memory in its initial user message and produce a second row.

<br>

## Blocked / open questions

- **Phase 4 constructor refactor**: the user has reverted my env-var fallback + fail-fast + `build_system_prompt()`-as-default refactor twice. The current `AgentCore.__init__` uses literal defaults (`model=MODEL_NAME`, `system_prompt=SYSTEM_PROMPT_PHASE0`). This means: (a) `RICH_SENPAI_MODEL` / `RICH_SENPAI_MAX_ITER` / `RICH_SENPAI_MAX_TOKENS` are documented in `SPEC.md §7` but not honored at runtime, (b) a missing `ANTHROPIC_API_KEY` will fail somewhere inside the Anthropic SDK rather than at construction, (c) the model still receives the terse PHASE0 prompt instead of the full README §3 directive set. Need user direction on whether to: (1) re-apply the refactor in a follow-up, (2) drop those acceptance criteria from Phase 4, or (3) take a different approach (e.g., a separate `AgentCore.from_env()` classmethod that does the env reading without changing the existing constructor).
- **LiteLLM vs raw Anthropic SDK**: not blocking, but flag the decision in `SPEC.md §8` once we have a real reason to switch.
- **Anthropic SDK >= 0.40.0**: confirmed `messages.create(system=..., tools=..., messages=..., max_tokens=...)` API and `response.content` block shape (`.type`, `.text`, `.name`, `.input`, `.id`). If the SDK ever changes block typing, the loop in §4 needs revisiting.

<br>

## Next concrete action

1. Real-API smoke (covers Phase 0 + 1 acceptance):
   ```
   echo 'ANTHROPIC_API_KEY=sk-...' > .env
   ./venv/bin/python main.py
   ```
   Expected: assistant text + ≥1 tool roundtrip, terminates on `wait` or `end_turn`, prints usage.

2. Resolve the Phase 4 constructor question above (re-apply env-var/fail-fast refactor, drop the acceptance, or `from_env()` classmethod).
3. Then start **Phase 5 — robustness**: retry helper around `messages.create` (3 attempts, exponential backoff, only retry on `APIConnectionError` / `RateLimitError` / `InternalServerError`); defensive parsing of malformed `tool_use.input`; tool-loop oscillation guard (3× same `(tool_name, input_hash)` → `stop_reason="tool_loop"`); per-cycle wall-clock budget → `stop_reason="timeout"`.
