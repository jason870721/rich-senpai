# read_inbox — drain the lead agent's inbox.
import json

from rich_senpai.core import state
from rich_senpai.tools.tool_result import ToolResult


SPEC = {
    "name": "read_inbox",
    "description": (
        "Drain the lead's inbox. Returns the messages as JSON; the file "
        "is emptied after the read."
    ),
    "input_schema": {"type": "object", "properties": {}},
}


def read_inbox() -> ToolResult:
    return ToolResult(text=json.dumps(state.BUS.read_inbox(state.LEAD_NAME), indent=2))
