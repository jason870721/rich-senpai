# task_get — fetch a task from the file-backed board.
from core import state


SPEC = {
    "name": "task_get",
    "description": "Get the full record of a file-backed task by id.",
    "input_schema": {
        "type": "object",
        "properties": {"task_id": {"type": "integer"}},
        "required": ["task_id"],
    },
}


def task_get(task_id: int) -> str:
    try:
        return state.TASK_MGR.get(int(task_id))
    except ValueError as exc:
        return f"error: {exc}"
