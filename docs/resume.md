# Resume — Self-Evolution Session

## Previous Sessions
1. **Session 1**: Raised `BASH_DEFAULT_TIMEOUT` 30→180s, `BG_DEFAULT_TIMEOUT` 120→360s; dropped "personal financial manager" identity; fixed typos in `tips.py`; added `replace_in_file` tool.
2. **Session 2**: Fixed `read_file` output format — removed `<n>\t` line-number prefix, now returns clean content.
3. **Session 3**: Fixed microcompact context loss — `compaction.py` now keeps content prefix instead of full elision.
4. **Session 4**: Fixed tool description drift in system prompt — compared every tool SPEC against hardcoded descriptions, fixed 3 mismatches, added 7 missing tools.
5. **Session 5**: Replaced hardcoded tool-usage section with data-driven `_render_tool_sections()` using `PROMPT_SECTIONS`. Removed hand-written duplication of SPEC descriptions from the prompt (-870 chars / ~218 tokens).

## Session 6
- **Added `offset`/`limit` to `read_file`**: The tool now accepts optional `offset` (1-based start line, default 1) and `limit` (max lines to return, default all). Header format improved: full reads show `[File: path (N lines)]`, slices show `[File: path (N lines), showing lines O-L]`. The model can now read large files efficiently without wasting tokens.
  - `read_file.py` — added params to SPEC and function; switched line counting from `str.count("\n")` to `str.splitlines()`; header reflects slice range; offset < 1 clamped to 1; offset past end returns "offset past end" note.
- **Created test suite foundation**: Installed pytest (already in `pyproject.toml` dev deps), created `tests/` directory, wrote 13 tests for `read_file` covering full reads, offset/limit slicing, edge cases (empty file, offset past end, offset clamped, single-line slice), and error paths (missing file, directory, binary).

## Last Session (Session 7)
- **Expanded file-access test coverage**: Wrote 32 new tests for the remaining file-access tools — `write_file`, `edit_file`, `replace_in_file`. Total suite now 45 tests, all passing in ~0.03s.
  - `tests/test_write_file.py` (9 tests) — new-file create (diff returned), overwrite (byte-count returned), parent-dir auto-create, empty file, custom encoding, missing-newline marker, write-to-directory failure, unwritable-parent failure (filesystem-permitting).
  - `tests/test_edit_file.py` (13 tests) — single-hunk replacement, pure addition, pure removal, multi-hunk, advisory-count auto-recount, pasted `--- a/` / `+++ b/` header passthrough (no double-prefix), parse errors (empty / malformed), apply errors (context mismatch / removal mismatch), file-unchanged-on-failure invariant, missing-file, directory-not-file.
  - `tests/test_replace_in_file.py` (10 tests) — single replacement, multi-line old_str, collapse/expand line counts, not-found, ambiguous (count > 1) rejected, ambiguity resolved by adding context, missing-file, directory-not-file, binary decode error.
- **Behaviour confirmed (not changed)**: `replace_in_file` does NOT support `replace_all` — multi-match is hard-rejected with a "make it unique" message. Documented in tests so future refactors don't accidentally drift.

## Files changed this session
- `tests/test_write_file.py` — new, 9 tests.
- `tests/test_edit_file.py` — new, 13 tests.
- `tests/test_replace_in_file.py` — new, 10 tests.
- `docs/resume.md` — this file.

## Next Priority Areas
1. **Finish tool tests**: Still un-covered — `bash` (subprocess-based; will need mocking or real-shell tests with timeouts), `grep`, `background_run` / `check_background`, plus delegation/messaging/task_board/web tools. Of these, `bash` is highest-value and trickiest because of subprocess + timeout behaviour.
2. **Non-tool unit tests**: `tools/tool_register.py::call_tool` dispatch, `compaction.py` (`microcompact`, `auto_compact`, `estimate_tokens`), `MessageBus` JSONL round-trip, `TaskManager` `blockedBy` cascade — all listed in revolution-plan M1.2.
3. **Path-traversal guard** (revolution-plan M1.4): With every file tool now under test, this is the safe moment to add a `WORKDIR`-relative check to `read_file` / `write_file` / `edit_file` / `replace_in_file`. Tests already in place will catch regressions.
4. **TUI UX**: Scrollback/search in the message panel, better visualization of tool call diffs, keybindings configurable via `~/.senpai/`.
5. **Subagent reliability**: `task` tool agents sometimes stall or produce incomplete results.

## Pain Points
- **microcompact** (Session 3, fixed): Was replacing entire tool result content with `[compacted: N chars elided]`. Fixed — now keeps a leading prefix.
- **read_file `<n>\t` prefix** (Session 2, fixed): Returned `<n>\t` line-number prefix. Fixed — now clean content.
- **tool description drift** (Session 5, fixed): Hardcoded tool sections could drift from tool SPECs. Replaced with `PROMPT_SECTIONS`; descriptions auto-derived.
- **read_file lacks offset/limit** (Session 6, fixed): Added `offset` (1-based start) and `limit` (max lines) parameters. Header shows range when slicing.
- **no test suite** (Sessions 6–7, in progress): All four file-access tools now covered (45 tests, 100% green). Remaining: `bash`, `grep`, `background_run`/`check_background`, delegation/messaging/task_board/web tools, and the non-tool units in revolution-plan M1.2.

## How to Restart
1. Read this file: `docs/resume.md`
2. Read `docs/revolition_plan.md` for the north star
3. Pick an area from "Next Priority Areas" above
4. Explore the relevant code, propose changes, implement, test
5. Update this file with progress before ending the session

## Getting Oriented
- **Entry point**: `src/rich_senpai/__main__.py`
- **Agent loop**: `src/rich_senpai/core/unit/agent/agent_core.py`
- **System prompt**: `src/rich_senpai/core/unit/agent/sys_prompt.py`
- **Compaction**: `src/rich_senpai/core/unit/agent/compaction.py`
- **Tools**: `src/rich_senpai/tools/` (organized by category)
- **Tool registry**: `src/rich_senpai/tools/tool_register.py`
- **TUI**: `src/rich_senpai/session_tui/`
- **Config**: `src/rich_senpai/core/config.py`
- **Tests**: `tests/`
