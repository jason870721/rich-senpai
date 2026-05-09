# broadcast — send a message to every spawned teammate.
from core import state


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


def broadcast(content: str) -> str:
    team = state.get_team()
    return state.BUS.broadcast(state.LEAD_NAME, content, team.member_names())
