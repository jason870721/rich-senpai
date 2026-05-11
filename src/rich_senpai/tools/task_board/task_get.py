# task_get — fetch a task from the file-backed board.
from rich_senpai.core import state
from rich_senpai.tools.tool_result import ToolResult


SPEC = {
    "name": "task_get",
    "description": "Get the full record of a file-backed task by id.",
    "input_schema": {
        "type": "object",
        "properties": {"task_id": {"type": "integer"}},
        "required": ["task_id"],
    },
}


def task_get(task_id: int) -> ToolResult:
    try:
        return ToolResult(text=state.TASK_MGR.get(int(task_id)))
    except ValueError as exc:
        return ToolResult(text=f"error: {exc}", ok=False)
