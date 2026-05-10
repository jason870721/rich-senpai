# claim_task — claim a file-backed task as the lead.
from core import state
from tools.tool_result import ToolResult


SPEC = {
    "name": "claim_task",
    "description": "Claim a pending task on the file-backed board for the lead.",
    "input_schema": {
        "type": "object",
        "properties": {"task_id": {"type": "integer"}},
        "required": ["task_id"],
    },
}


def claim_task(task_id: int) -> ToolResult:
    try:
        return ToolResult(text=state.TASK_MGR.claim(int(task_id), state.LEAD_NAME))
    except ValueError as exc:
        return ToolResult(text=f"error: {exc}", ok=False)
