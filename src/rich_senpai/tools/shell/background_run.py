# background_run tool — fire a shell command without blocking the agent loop.
from rich_senpai.core import state
from rich_senpai.core.config import BG_DEFAULT_TIMEOUT
from rich_senpai.tools.tool_result import ToolResult


SPEC = {
    "name": "background_run",
    "description": (
        "Run a shell command in a background thread. Returns immediately "
        "with a `task_id=<id>` line you can use later. When the command "
        "finishes, a short preview (~500 chars) of its output is "
        "auto-surfaced to you on the next turn via a <background-results> "
        "block — you don't need to poll. For the full output (up to 50k "
        "chars) or to check status mid-run, call check_background(task_id)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to run (executed via /bin/sh -c).",
            },
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


def background_run(command: str, timeout: int = BG_DEFAULT_TIMEOUT) -> ToolResult:
    # Failure of the spawned command itself surfaces later via a
    # background-results notification; this call only kicks off the
    # worker thread and is effectively always successful.
    return ToolResult(text=state.BG.run(command, timeout=timeout))
