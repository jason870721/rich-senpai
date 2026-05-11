# list_teammates — show every teammate and their current status.
from rich_senpai.core import state
from rich_senpai.tools.tool_result import ToolResult


SPEC = {
    "name": "list_teammates",
    "description": "List every spawned teammate with their role and status.",
    "input_schema": {"type": "object", "properties": {}},
}


def list_teammates() -> ToolResult:
    return ToolResult(text=state.get_team().list_all())
