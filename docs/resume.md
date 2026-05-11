# Resume — Self-Evolution Session

## Previous Sessions
1. **Session 1**: Raised `BASH_DEFAULT_TIMEOUT` 30→180s, `BG_DEFAULT_TIMEOUT` 120→360s; dropped "personal financial manager" identity; fixed typos in `tips.py`; added `replace_in_file` tool.
2. **Session 2**: Fixed `read_file` output format — removed `<n>\t` line-number prefix, now returns clean content.
3. **Session 3**: Fixed microcompact context loss — `compaction.py` now keeps content prefix instead of full elision.
4. **Session 4**: Fixed tool description drift in system prompt — compared every tool SPEC against hardcoded descriptions, fixed 3 mismatches, added 7 missing tools (`## Messaging` and `## Skills` sections).

## This Session (Session 5)
- **Structural tool-description fix**: Replaced the hardcoded tool-usage section in `build_system_prompt()` with a data-driven `_render_tool_sections()` function. Tool listings and section structure are now defined in a `PROMPT_SECTIONS` data structure — adding a tool only requires adding ONE entry to the list, not editing a giant f-string. Tool descriptions are auto-derived from `TOOL_SPECS` via `_td()`.
- **Removed duplication**: Hand-written usage tips that repeated SPEC descriptions verbatim were removed (replace_in_file "Copy the exact text…", edit_file "`diff` is one or more unified hunks…", write_file "For in-place edits…", TodoWrite "Mark exactly one item…", wait/background_run config values). The prompt dropped from 16,998 to 16,128 chars (-870 chars / ~218 tokens).
- All 29 tools verified to appear exactly once in the generated prompt.

## Files changed this session
- `src/rich_senpai/core/unit/agent/sys_prompt.py` — added `_render_tool_sections()` with `PROMPT_SECTIONS` data structure; replaced hardcoded tool sections with `{tool_sections}` interpolation; removed 4 unused config locals.
- `docs/resume.md` — this file

## Next Priority Areas
1. **TUI UX**: Scrollback/search in the message panel, better visualization of tool call diffs in the TUI, keybindings configurable via `~/.senpai/`.
2. **Subagent reliability**: `task` tool agents sometimes stall or produce incomplete results.
3. **Tests**: No test suite exists. This is also revolution-plan Milestone 1.
4. **Revolution plan items**: See `docs/revolition_plan.md` — packaging, CI, lint, real API integration.

## Pain Points
*(Tool issues logged so the next session can fix them.)*

- **microcompact** (Session 3, fixed): Was replacing entire tool result content with `[compacted: N chars elided]`, losing all context. Fixed by keeping a leading prefix of the content.
- **read_file** (Session 2, fixed): Returned `<n>\t` line-number prefix. Fixed — now clean content.
- **tool description drift** (Session 5, fixed): Hardcoded tool sections in `sys_prompt.py` could drift from tool SPECs. Replaced with data-driven `PROMPT_SECTIONS` structure; descriptions auto-derive from `TOOL_SPECS` via `_td()`. Adding a tool now only requires a single entry in `_render_tool_sections()`.
- **read_file lacks offset/limit** (open): `read_file` has no `offset` or `limit` parameter — it always returns the full file. For large files this wastes tokens. The model keeps trying to use `offset` because that's what most file-reader APIs support.
- **no test suite** (open): The project has zero tests. Adding even a basic smoke test would catch regressions early.

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
