# read_file tool — returns clean file content with a compact header.
#
# No line-number prefixing — the LLM gets raw content it can use directly
# in diffs. Line count and range are noted in the header.
from pathlib import Path

from rich_senpai.tools.tool_result import ToolResult


SPEC = {
    "name": "read_file",
    "description": (
        "Read the contents of a local text file and return clean content "
        "with a `[path (N lines)]` header. Lines are NOT numbered inline — "
        "they are raw content ready to copy into diff bodies. Determine "
        "line numbers by counting from the first returned line (line 1)."
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
        },
        "required": ["path"],
    },
}


def read_file(path: str, encoding: str = "utf-8") -> ToolResult:
    file_path = Path(path).expanduser()
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

    # Count lines for the header
    line_count = contents.count("\n")
    if contents and not contents.endswith("\n"):
        line_count += 1

    resolved = str(file_path.resolve())
    header = f"[File: {resolved}, {line_count} lines]"
    return ToolResult(text=f"{header}\n{contents.rstrip('\n')}")
