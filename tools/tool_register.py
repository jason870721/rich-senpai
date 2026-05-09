# register all agent tool here
from typing import Any, Callable

from tools import bash, http_request, read_file, write_file


SYS_TOOL_PROMPT = """
You have access to a small set of local tools that operate on the user's
machine:

- read_file: read the contents of a local text file.
- write_file: create or overwrite a local file with the given content.
- bash: run a shell command and capture its stdout, stderr, and exit code.
- http_request: send an HTTP request and return the response.

Use the narrowest tool that fits the task. Prefer read_file over bash for
inspecting files, and prefer write_file over bash for creating files. Never
run destructive shell commands (rm -rf, force pushes, dropping data, etc.)
without explicit confirmation from the user.
""".strip()


TOOL_SPECS: list[dict[str, Any]] = [
    read_file.SPEC,
    write_file.SPEC,
    bash.SPEC,
    http_request.SPEC,
]

TOOL_HANDLERS: dict[str, Callable[..., str]] = {
    read_file.SPEC["name"]: read_file.read_file,
    write_file.SPEC["name"]: write_file.write_file,
    bash.SPEC["name"]: bash.bash,
    http_request.SPEC["name"]: http_request.http_request,
}


def call_tool(name: str, arguments: dict[str, Any] | None = None) -> str:
    """Dispatch a tool call by name. Returns the tool's string output, or an
    error string if the tool name is unknown or arguments are invalid."""
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return f"error: unknown tool '{name}'"
    try:
        return handler(**(arguments or {}))
    except TypeError as exc:
        return f"error: invalid arguments for '{name}': {exc}"
