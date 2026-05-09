# bash tool
import subprocess


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
                "description": "Maximum seconds to wait before killing the command. Defaults to 30.",
            },
            "cwd": {
                "type": "string",
                "description": "Working directory to run the command in. Defaults to the current process cwd.",
            },
        },
        "required": ["command"],
    },
}


def bash(command: str, timeout: float = 30, cwd: str | None = None) -> str:
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
        return f"error: command timed out after {timeout}s: {command}"
    except OSError as exc:
        return f"error: could not run command: {exc}"

    return (
        f"exit_code: {result.returncode}\n"
        f"--- stdout ---\n{result.stdout}"
        f"--- stderr ---\n{result.stderr}"
    )
