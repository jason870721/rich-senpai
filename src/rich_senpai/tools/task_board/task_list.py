# task_list — list every file-backed task.
from rich_senpai.core import state
from rich_senpai.tools.tool_result import ToolResult


SPEC = {
    "name": "task_list",
    "description": "List every task on the file-backed board.",
    "input_schema": {"type": "object", "properties": {}},
}


def task_list() -> ToolResult:
    return ToolResult(text=state.TASK_MGR.list_all())
