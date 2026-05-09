# TodoWrite tool — overwrite the in-process todo list.
from typing import Any

from core import state


SPEC = {
    "name": "TodoWrite",
    "description": (
        "Overwrite the working todo list. Use for short, in-session "
        "checklists; for durable cross-session work prefer task_create."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed"],
                        },
                        "activeForm": {"type": "string"},
                    },
                    "required": ["content", "status", "activeForm"],
                },
            }
        },
        "required": ["items"],
    },
}


def todo_write(items: list[dict[str, Any]]) -> str:
    try:
        return state.TODO.update(items)
    except ValueError as exc:
        return f"error: {exc}"
