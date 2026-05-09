# read_inbox — drain the lead agent's inbox.
import json

from core import state


SPEC = {
    "name": "read_inbox",
    "description": (
        "Drain the lead's inbox. Returns the messages as JSON; the file "
        "is emptied after the read."
    ),
    "input_schema": {"type": "object", "properties": {}},
}


def read_inbox() -> str:
    return json.dumps(state.BUS.read_inbox(state.LEAD_NAME), indent=2)
