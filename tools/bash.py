# bash tool
import subprocess

from core.config import BASH_DEFAULT_TIMEOUT
from tools.tool_result import ToolResult


SPEC = {
    "name": "bash",
    "description": (
        "Execute a shell command via /bin/bash and return its combined "
        "stdout, stderr, and exit status. Use for build commands, tests, "
        "git operations, and other shell tasks. Avoid destructive commands "
        "(rm -rf, force pushes, etc.) without explicit user confirmation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
            },
            "timeout": {
                "type": "number",
                "description": (
                    f"Maximum seconds to wait before killing the command. "
                    f"Defaults to {BASH_DEFAULT_TIMEOUT} (BASH_DEFAULT_TIMEOUT)."
                ),
            },
            "cwd": {
                "type": "string",
                "description": "Working directory to run the command in. Defaults to the current process cwd.",
            },
        },
        "required": ["command"],
    },
}


def bash(command: str, timeout: float = BASH_DEFAULT_TIMEOUT, cwd: str | None = None) -> ToolResult:
    """Run a shell command and return a structured result.

    `ok` is True only when the process exited with code 0; non-zero
    exits, timeouts, and OSError all surface as `ok=False` so the TUI
    can render the result body in red. Output format:

        exit_code: <N>
        <stdout, if any>
        <stderr, if any>
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            executable="/bin/bash",
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(
            text=f"error: command timed out after {timeout}s: {command}",
            ok=False,
        )
    except OSError as exc:
        return ToolResult(text=f"error: could not run command: {exc}", ok=False)

    parts = [f"exit_code: {result.returncode}"]
    stdout = result.stdout.rstrip()
    stderr = result.stderr.rstrip()
    if stdout:
        parts.append(stdout)
    if stderr:
        parts.append(stderr)
    return ToolResult(text="\n".join(parts), ok=(result.returncode == 0))
