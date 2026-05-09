# spawn_teammate — start a persistent autonomous teammate.
from core import state


SPEC = {
    "name": "spawn_teammate",
    "description": (
        "Spawn a persistent autonomous teammate that runs its own ReAct "
        "loop in a background thread, communicates via the message bus, "
        "and auto-claims unclaimed tasks while idle."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "role": {"type": "string"},
            "prompt": {
                "type": "string",
                "description": "Initial brief for the teammate.",
            },
        },
        "required": ["name", "role", "prompt"],
    },
}


def spawn_teammate(name: str, role: str, prompt: str) -> str:
    return state.get_team().spawn(name, role, prompt)
