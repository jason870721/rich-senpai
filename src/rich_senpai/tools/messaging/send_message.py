# send_message — send a message to a named teammate.
from rich_senpai.core import state
from rich_senpai.core.unit.team.messaging import VALID_MSG_TYPES
from rich_senpai.tools.tool_result import ToolResult


SPEC = {
    "name": "send_message",
    "description": (
        "Send a message to a named teammate's inbox. Default msg_type is "
        "'message'. Use 'shutdown_request' to ask a teammate to stop, or "
        "'plan_approval_response' from inside an approval flow."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "to": {"type": "string"},
            "content": {"type": "string"},
            "msg_type": {
                "type": "string",
                "enum": sorted(VALID_MSG_TYPES),
            },
        },
        "required": ["to", "content"],
    },
}


def send_message(to: str, content: str, msg_type: str = "message") -> ToolResult:
    if msg_type not in VALID_MSG_TYPES:
        return ToolResult(text=f"error: unknown msg_type '{msg_type}'", ok=False)
    return ToolResult(text=state.BUS.send(state.LEAD_NAME, to, content, msg_type=msg_type))
