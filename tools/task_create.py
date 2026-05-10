# task_create — create a persistent file-backed task.
from core import state
from tools.tool_result import ToolResult


SPEC = {
    "name": "task_create",
    "description": (
        "Create a persistent task on the file-backed board. Tasks survive "
        "process restarts and are visible to teammates so they can be "
        "claimed and worked on autonomously."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "subject": {"type": "string"},
            "description": {"type": "string"},
        },
        "required": ["subject"],
    },
}


def task_create(subject: str, description: str = "") -> ToolResult:
    return ToolResult(text=state.TASK_MGR.create(subject, description))
