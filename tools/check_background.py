# check_background tool — inspect background task status.
from core import state


SPEC = {
    "name": "check_background",
    "description": (
        "Inspect background tasks. Pass task_id to see one task's "
        "status and result, or omit it to list all tracked tasks."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Background task id returned by background_run.",
            }
        },
    },
}


def check_background(task_id: str | None = None) -> str:
    return state.BG.check(task_id)
