# Resume — Self-Evolution Session

## Previous Sessions
1. **Session 1**: Raised `BASH_DEFAULT_TIMEOUT` 30→180s, `BG_DEFAULT_TIMEOUT` 120→360s; dropped "personal financial manager" identity; fixed typos in `tips.py`; added `replace_in_file` tool.
2. **Session 2**: Fixed `read_file` output format — removed `<n>\t` line-number prefix, now returns clean content.
3. **Session 3**: Fixed microcompact context loss — `compaction.py` now keeps content prefix instead of full elision.

## This Session (Session 4)
- **Fixed tool description drift in system prompt**: Compared every tool SPEC against the hardcoded descriptions in `sys_prompt.py`. Fixed 3 mismatches (background_run lacked auto-surface info, idle lacked "lead does not idle", update_short_memory lacked token cap) and added missing descriptions for 7 tools (send_message, read_inbox, broadcast, list_teammates, shutdown_request, plan_approval, load_skill). Added new `## Messaging` and `## Skills` sections.
- Verified `build_system_prompt()` still builds cleanly (9768 chars).

## Files changed this session
- `src/rich_senpai/core/unit/agent/sys_prompt.py` — updated 3 mismatched descriptions; added 7 missing tool sub-sections; added `## Messaging` and `## Skills` sections
- `docs/resume.md` — this file

## Next Priority Areas
1. **Structural tool-description fix**: The system prompt still has hardcoded tool descriptions that duplicate tool SPECs. Consider auto-generating the tool-usage section from `TOOL_SPECS` at build time so drift becomes impossible. A middle-ground: keep hand-written usage patterns/pitfalls but auto-derive the one-liner descriptions.
2. **TUI UX**: Scrollback/search in the message panel, better visualization of tool call diffs in the TUI, keybindings configurable via `~/.senpai/`.
3. **Subagent reliability**: `task` tool agents sometimes stall or produce incomplete results.
4. **Tests**: No test suite exists.
5. **Revolution plan items**: See `docs/revolition_plan.md` — mid-term items include TDD, coverage, and real API integration.

## Pain Points
*(Tool issues logged so the next session can fix them.)*

- **microcompact** (Session 3, fixed): Was replacing entire tool result content with `[compacted: N chars elided]`, losing all context. Fixed by keeping a leading prefix of the content.
- **read_file** (Session 2, fixed): Returned `<n>\t` line-number prefix. Fixed — now clean content.
- **tool description drift** (Session 4, partially fixed): Hardcoded descriptions in sys_prompt.py drift from tool SPECs. Manually re-synced, but the structural problem remains — see "Next Priority Areas" #1.

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
