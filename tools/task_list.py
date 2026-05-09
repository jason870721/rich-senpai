# task_list — list every file-backed task.
from core import state


SPEC = {
    "name": "task_list",
    "description": "List every task on the file-backed board.",
    "input_schema": {"type": "object", "properties": {}},
}


def task_list() -> str:
    return state.TASK_MGR.list_all()
