# read_file tool — Claude Code style cat -n output.
#
# Each returned line is prefixed with `<line>\t` (right-aligned 6-char
# column + tab). The agent uses these line numbers to reason about
# location; when authoring an edit the prefix MUST be stripped from
# old_string. After a successful read the path is registered with the
# session ReadTracker so edit_file/write_file can verify it was loaded.

from rich_senpai.tools.file_access._guard import PathOutsideWorkdirError, resolve_safe
from rich_senpai.tools.file_access._session import get_tracker
from rich_senpai.tools.tool_result import ToolResult


SPEC = {
    "name": "read_file",
    "description": (
        "Reads a file from the local filesystem. Output is cat -n format: "
        "each line is prefixed with its 1-based line number and a tab "
        "(e.g. `   42\\thello`). A header `[File: <path> (N lines)]` "
        "precedes the body and notes the slice when offset/limit are used.\n"
        "\n"
        "Use `offset` (1-based) and `limit` to read a slice of a large "
        "file without spending tokens on the rest. Reading marks the file "
        "as loaded into the session — edit_file and write_file (overwrite) "
        "refuse to touch a file you haven't read first.\n"
        "\n"
        "When you later call edit_file, DO NOT include the `<line>\\t` "
        "prefix in old_string — strip it. Only the raw line content is "
        "what's actually in the file. Access outside the workdir is denied "
        "unless allow_outside_workdir is set to true."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or relative path to the file to read.",
            },
            "encoding": {
                "type": "string",
                "description": "Text encoding to decode the file with. Defaults to utf-8.",
            },
            "offset": {
                "type": "integer",
                "description": "1-based line number to start reading from. Defaults to 1.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to return. Defaults to all lines.",
            },
            "allow_outside_workdir": {
                "type": "boolean",
                "description": (
                    "Allow reading files outside the project workdir. "
                    "Defaults to false — the tool will refuse to read "
                    "/etc/passwd, ~/.ssh, etc."
                ),
            },
        },
        "required": ["path"],
    },
}


def _format_lines(lines: list[str], start_lineno: int) -> str:
    """Format lines with cat -n style prefix: `<6-wide lineno>\\t<content>`."""
    return "\n".join(
        f"{start_lineno + i:>6}\t{line}" for i, line in enumerate(lines)
    )


def read_file(
    path: str,
    encoding: str = "utf-8",
    offset: int = 1,
    limit: int | None = None,
    allow_outside_workdir: bool = False,
) -> ToolResult:
    try:
        file_path = resolve_safe(path, allow_outside_workdir=allow_outside_workdir)
    except PathOutsideWorkdirError as exc:
        return ToolResult(text=f"error: {exc}", ok=False)
    if not file_path.exists():
        return ToolResult(text=f"error: file not found: {path}", ok=False)
    if not file_path.is_file():
        return ToolResult(text=f"error: not a regular file: {path}", ok=False)
    try:
        contents = file_path.read_text(encoding=encoding)
    except UnicodeDecodeError as exc:
        return ToolResult(
            text=f"error: could not decode {path} as {encoding}: {exc}",
            ok=False,
        )
    except OSError as exc:
        return ToolResult(text=f"error: could not read {path}: {exc}", ok=False)

    all_lines = contents.splitlines(keepends=False)
    total_lines = len(all_lines)
    resolved = str(file_path.resolve())

    tracker = get_tracker()
    if tracker is not None:
        tracker.mark_read(file_path)

    if total_lines == 0:
        return ToolResult(text=f"[File: {resolved}, 0 lines]")

    start = max(offset, 1) - 1
    if start >= total_lines:
        return ToolResult(
            text=(
                f"[File: {resolved} ({total_lines} lines), showing lines "
                f"{start + 1}-{total_lines} (offset past end)]"
            )
        )

    end = min(start + limit, total_lines) if limit is not None else total_lines
    selected = all_lines[start:end]

    if start == 0 and end == total_lines:
        header = f"[File: {resolved} ({total_lines} lines)]"
    else:
        header = (
            f"[File: {resolved} ({total_lines} lines), "
            f"showing lines {start + 1}-{end}]"
        )

    body = _format_lines(selected, start + 1)
    return ToolResult(text=f"{header}\n{body}")
