# recover_compacted_tool_use_result — sentinel tool intercepted by every
# ReAct loop. The actual lookup runs inside the loop's `_dispatch_tool_uses`
# branch because the recovery map lives per-instance (one per AgentCore /
# subagent / teammate). This handler exists only so `tool_register` has a
# callable to register; it should never actually execute.
from rich_senpai.tools.tool_result import ToolResult


SPEC = {
    "name": "recover_compacted_tool_use_result",
    "description": (
        "Restore the full original content of a tool_use_result that was "
        "previously compacted by microcompact. Pass the `tool_use_id` — "
        "you'll find it in the compacted stub between the square brackets "
        "(`...recover_compacted_tool_use_result(tool_use_id=\"<id>\")...`). "
        "Returns the full original output. Call this when a compacted "
        "stub no longer carries enough information for the work ahead — "
        "do NOT call it speculatively, since recovered content is large "
        "and re-inflates token use."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "tool_use_id": {
                "type": "string",
                "description": (
                    "The id of the tool_use whose result you need restored. "
                    "Quoted verbatim from the compacted stub's restore hint."
                ),
            },
        },
        "required": ["tool_use_id"],
    },
}


def recover_compacted_tool_use_result(tool_use_id: str) -> ToolResult:
    """Fallback handler — never expected to run. Each agent loop intercepts
    the tool name before dispatch and reads from its own recovery_map.
    Returning an error here makes a broken interception path visible."""
    return ToolResult(
        text=(
            f"error: recover_compacted_tool_use_result for id={tool_use_id!r} "
            "was dispatched to the registry fallback, which has no access "
            "to the per-loop recovery map. The agent loop's interception "
            "path is broken."
        ),
        ok=False,
    )
