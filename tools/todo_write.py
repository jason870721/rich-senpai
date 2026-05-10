# TodoWrite tool — overwrite the in-process todo list.
from typing import Any

from core import state
from tools.tool_result import ToolResult


SPEC = {
    "name": "TodoWrite",
    "description": (
        "Overwrite the working todo list for the current session. "
        "Use it to plan and track multi-step work (3+ steps, branching, "
        "or anything spanning multiple tool calls). Skip it for single-"
        "step tasks. Each item needs `content` (imperative form), "
        "`activeForm` (present-continuous, shown while in_progress), and "
        "`status` (pending|in_progress|completed). Only one item may be "
        "in_progress at a time. Mark items completed as soon as the work "
        "is done — don't batch. The list is in-process only; for durable "
        "cross-session work use task_create instead."
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


def todo_write(items: list[dict[str, Any]]) -> ToolResult:
    try:
        return ToolResult(text=state.TODO.update(items))
    except ValueError as exc:
        return ToolResult(text=f"error: {exc}", ok=False)
