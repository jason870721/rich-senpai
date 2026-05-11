# read_file tool — returns clean file content with a compact header.
#
# No line-number prefixing — the LLM gets raw content it can use directly
# in diffs. Line count and range are noted in the header.

from rich_senpai.tools.file_access._guard import PathOutsideWorkdirError, resolve_safe
from rich_senpai.tools.tool_result import ToolResult


SPEC = {
    "name": "read_file",
    "description": (
        "Read the contents of a local text file and return clean content "
        "with a `[path (N lines)]` header. Lines are NOT numbered inline — "
        "they are raw content ready to copy into diff bodies. Determine "
        "line numbers by counting from the first returned line (line 1). "
        "Use `offset` and `limit` to read a slice of a large file without "
        "wasting tokens. Access outside the workdir is denied unless "
        "allow_outside_workdir is set to true."
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

    # Split into lines for offset/limit support
    all_lines = contents.splitlines(keepends=False)
    total_lines = len(all_lines)

    if total_lines == 0:
        resolved = str(file_path.resolve())
        return ToolResult(text=f"[File: {resolved}, 0 lines]")

    # Clamp offset to 1-based; convert to 0-based index
    start = max(offset, 1) - 1
    if start >= total_lines:
        resolved = str(file_path.resolve())
        return ToolResult(
            text=f"[File: {resolved} ({total_lines} lines), showing lines "
            f"{start + 1}-{total_lines} (offset past end)]"
        )

    end = min(start + limit, total_lines) if limit is not None else total_lines
    selected = all_lines[start:end]

    resolved = str(file_path.resolve())
    if start == 0 and end == total_lines:
        header = f"[File: {resolved} ({total_lines} lines)]"
    else:
        header = (
            f"[File: {resolved} ({total_lines} lines), "
            f"showing lines {start + 1}-{end}]"
        )

    return ToolResult(text=f"{header}\n" + "\n".join(selected))
