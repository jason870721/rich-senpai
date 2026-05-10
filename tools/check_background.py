# check_background tool — inspect background task status.
from core import state
from tools.tool_result import ToolResult


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


def check_background(task_id: str | None = None) -> ToolResult:
    text = state.BG.check(task_id)
    # BackgroundManager.check uses an "Unknown background task: <id>"
    # sentinel for missing ids — surface that as a failed lookup so
    # the TUI flags it red.
    ok = not text.startswith("Unknown background task")
    return ToolResult(text=text, ok=ok)
