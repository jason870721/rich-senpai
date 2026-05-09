# background_run tool — fire a shell command without blocking the agent loop.
from core import state
from core.config import BG_DEFAULT_TIMEOUT


SPEC = {
    "name": "background_run",
    "description": (
        "Run a shell command in a background thread. Returns immediately "
        "with a short task id. Completion notifications are surfaced to "
        "the agent on the next turn; check status explicitly via "
        "check_background(task_id)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "timeout": {
                "type": "integer",
                "description": (
                    f"Maximum seconds before the command is killed. "
                    f"Defaults to {BG_DEFAULT_TIMEOUT} (BG_DEFAULT_TIMEOUT)."
                ),
            },
        },
        "required": ["command"],
    },
}


def background_run(command: str, timeout: int = BG_DEFAULT_TIMEOUT) -> str:
    return state.BG.run(command, timeout=timeout)
