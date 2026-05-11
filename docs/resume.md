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

## Session 7
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

## Session 8
- **Path-traversal guard (M1.4)**: Added `_guard.py` in file_access with `resolve_safe()`, `_is_within()`, `PathOutsideWorkdirError`. All four file tools (`read_file`, `write_file`, `edit_file`, `replace_in_file`) now accept optional `allow_outside_workdir: bool = False` — defaults deny access outside `config.WORKDIR`. 16 new tests in `tests/test_guard.py` cover guard logic and integration with each tool.
  - All four file-access tools updated with import, SPEC param, function param, and `resolve_safe()` call.
  - Existing tests require `allow_outside_workdir=True` on all file-access tool calls (temp dirs are outside WORKDIR).
- **background_run / check_background tests**: 18 tests in `tests/test_background.py` — task_id generation, command truncation, unknown task error, list-all, completion/error/timeout status, drain, reset. Tests use lazy imports (`_br()` / `_cb()` helpers) to avoid circular imports from `core.state → tool_register`.
  - Fixed `BackgroundManager` thread leak: added `_threads` tracking + `shutdown()` + resilient `_exec` (no crash if task already cleaned up).
  - Fixed `reset()`: no longer replaces `_lock`/`Queue` (broken for in-flight threads).
- **TUI bug fix**: `widgets.py::action_submit_input` no longer blocks empty Enter — fixes max_iterations "press enter to continue" being broken.
- **`compaction.py` tests**: 24 tests — `estimate_tokens` (5), `_make_stub` (5), `_resolve_original` (4), `microcompact` (10). Covers token estimation, progressive tier compaction, recovery map, idempotency, assistant-turn exclusion, min_len bypass.
- **`call_tool` dispatch tests**: 7 async tests — unknown tool, bad args, sync dispatch via thread, ToolResult passthrough, failure passthrough. Lazy import with pre-heat to sidestep circular import.
- **Test suite**: 134 tests, all passing.

### Files changed this session
- `src/rich_senpai/tools/file_access/_guard.py` — new.
- `src/rich_senpai/tools/file_access/read_file.py` — path guard.
- `src/rich_senpai/tools/file_access/write_file.py` — path guard.
- `src/rich_senpai/tools/file_access/edit_file.py` — path guard.
- `src/rich_senpai/tools/file_access/replace_in_file.py` — path guard.
- `src/rich_senpai/core/unit/manager/background.py` — thread tracking, shutdown, resilient _exec, fixed reset.
- `src/rich_senpai/session_tui/widgets.py` — allow empty Enter.
- `tests/test_guard.py` — new, 16 tests.
- `tests/test_background.py` — new, 18 tests.
- `tests/test_compaction.py` — new, 24 tests.
- `tests/test_tool_register.py` — new, 7 tests.
- `tests/test_read_file.py`, `test_write_file.py`, `test_edit_file.py`, `test_replace_in_file.py` — add `allow_outside_workdir=True`.
- `docs/resume.md` — this file.

## Session 9
- **MessageBus tests (M1.2)**: 13 tests — send+read_inbox round-trip, drain, empty inbox, message_type preservation, extra_fields, multi-recipient isolation, send return value, JSONL format, broadcast to multiple, broadcast skip sender, broadcast empty/solo list, inbox_dir creation. (`tests/test_messaging.py` — new)
- **TaskManager tests (M1.2)**: 22 tests — create+get (id auto-increment, JSON round-trip), get nonexistent (raises ValueError), file-backed persistence across instances, status transitions (pending→in_progress→completed), add/remove blockedBy (dedup, sort), blockedBy cascade on completion (removes blocker ID from all dependents), claim (sets owner+in_progress), list_all (glyphs, owner, blocked), list_unclaimed (excludes completed/claimed/blocked), delete (removes file), tasks_dir creation. (`tests/test_tasks_file.py` — new)
- **DiffParser tests (M1.2)**: 25 tests — simple/multi-hunk parsing, auto-recount, `\ No newline` marker skip, pure insertion/deletion, file-header preamble passthrough, empty-body error, empty-diff error, bad-body-line error, simple change apply, insertion/deletion apply, multi-hunk apply, fuzzy match (±20 lines), removal-mismatch error, context-mismatch error, trailing/no-trailing newline preservation. (`tests/test_diff.py` — new)
- **SkillLoader tests (M1.2)**: 10 tests — descriptions empty/shows names/shows first-line-as-description, load wraps in `<skill>` tags, unknown skill returns error string, load caches (file changes invisible after first load), reload refreshes, multi-skill loads, directory-name-as-key, skills_dir auto-created. (`tests/test_skills.py` — new)
- **Total**: 204 tests, all passing (70 new this session).

### Pain Points (this session)
- **Circular import: MessageBus from `core.unit.team.messaging`**: `team/__init__.py` → `team.py` → `compaction.py` → `agent_core.py` → `state.py` → `team/__init__.py`. Direct import of `messaging.py` triggers the cycle because `state.py` needs `TeammateManager` which hasn't been defined yet. Workaround: import from `core.state` instead. Root fix: break the cycle — lazy-import in `state.py` or move `TeammateManager` to its own module.
- **SkillLoader scans on `__init__`, not lazily**: Skills must exist on disk BEFORE `SkillLoader()` is called. Tests that write files after construction silently find nothing. Design smell: init-time side effect makes testing awkward.
- **SkillLoader.load() returns error string, doesn't raise**: Unlike `TaskManager.get()` (raises `ValueError`), `SkillLoader.load()` returns `"error: unknown skill 'X'"`. Inconsistent error-handling convention across internal units.

### Files changed this session
- `tests/test_messaging.py` — new, 13 tests.
- `tests/test_tasks_file.py` — new, 22 tests.
- `tests/test_diff.py` — new, 25 tests.
- `tests/test_skills.py` — new, 10 tests.
- `docs/resume.md` — this file.

## Next Priority Areas
1. **Finish tool tests**: `grep` (tool itself doesn't exist yet — needs creation per M2.1), delegation/messaging/task_board/web tools.
2. **Non-tool unit tests**: M1.2 core now tested (MessageBus, TaskManager, DiffParser, SkillLoader). Gaps remain: TUI tests (Textual), integration test with async LLMClient mock.
3. **TUI UX**: Scrollback/search in the message panel, better visualization of tool call diffs, keybindings configurable via `~/.senpai/`.
4. **Subagent reliability**: `task` tool agents sometimes stall or produce incomplete results.
5. **Fix circular import**: `state.py` → `team/__init__.py` → `team.py` → `agent_core.py` → `state.py`. Lazy-import or restructure.

## Pain Points
- **Circular import (Session 9, unfixed)**: `team/__init__.py` → `team.py` → ... → `state.py` → `team/__init__.py`. Blocked direct MessageBus import in tests; worked around via `core.state`.
- **SkillLoader init-time scan (Session 9, unfixed)**: Skills must exist before construction; init-then-write silently yields "(no skills)".
- **SkillLoader.load error convention (Session 9, unfixed)**: Returns error string instead of raising — inconsistent with TaskManager.
- **microcompact** (Session 3, fixed): Was replacing entire tool result content with `[compacted: N chars elided]`. Fixed — now keeps a leading prefix.
- **read_file `<n>\t` prefix** (Session 2, fixed): Returned `<n>\t` line-number prefix. Fixed — now clean content.
- **tool description drift** (Session 5, fixed): Hardcoded tool sections could drift from tool SPECs. Replaced with `PROMPT_SECTIONS`; descriptions auto-derived.
- **read_file lacks offset/limit** (Session 6, fixed): Added `offset` (1-based start) and `limit` (max lines) parameters. Header shows range when slicing.

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
