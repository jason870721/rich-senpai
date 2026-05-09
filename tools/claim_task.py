# claim_task — claim a file-backed task as the lead.
from core import state


SPEC = {
    "name": "claim_task",
    "description": "Claim a pending task on the file-backed board for the lead.",
    "input_schema": {
        "type": "object",
        "properties": {"task_id": {"type": "integer"}},
        "required": ["task_id"],
    },
}


def claim_task(task_id: int) -> str:
    try:
        return state.TASK_MGR.claim(int(task_id), state.LEAD_NAME)
    except ValueError as exc:
        return f"error: {exc}"
