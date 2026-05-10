# broadcast — send a message to every spawned teammate.
from core import state
from tools.tool_result import ToolResult


SPEC = {
    "name": "broadcast",
    "description": (
        "Send the same message to every currently spawned teammate "
        "(everyone except the lead)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"content": {"type": "string"}},
        "required": ["content"],
    },
}


def broadcast(content: str) -> ToolResult:
    team = state.get_team()
    return ToolResult(text=state.BUS.broadcast(state.LEAD_NAME, content, team.member_names()))
