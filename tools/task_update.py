# task_update — update status / dependencies of a file-backed task.
from core import state
from tools.tool_result import ToolResult


SPEC = {
    "name": "task_update",
    "description": (
        "Update status or dependency edges of a file-backed task. "
        "Marking a task completed automatically removes it from any "
        "other task's blockedBy list. Use status='deleted' to remove."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": {"type": "integer"},
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "completed", "deleted"],
            },
            "add_blocked_by": {
                "type": "array",
                "items": {"type": "integer"},
            },
            "remove_blocked_by": {
                "type": "array",
                "items": {"type": "integer"},
            },
        },
        "required": ["task_id"],
    },
}


def task_update(
    task_id: int,
    status: str | None = None,
    add_blocked_by: list[int] | None = None,
    remove_blocked_by: list[int] | None = None,
) -> ToolResult:
    try:
        return ToolResult(
            text=state.TASK_MGR.update(
                int(task_id),
                status=status,
                add_blocked_by=add_blocked_by,
                remove_blocked_by=remove_blocked_by,
            ),
        )
    except ValueError as exc:
        return ToolResult(text=f"error: {exc}", ok=False)
