# read file tool
from pathlib import Path

from tools.tool_result import ToolResult


SPEC = {
    "name": "read_file",
    "description": (
        "Read the contents of a local text file and return it as a string. "
        "Use this to inspect source code, configuration, logs, or any other "
        "text on the user's machine."
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
        return ToolResult(text=file_path.read_text(encoding=encoding))
    except UnicodeDecodeError as exc:
        return ToolResult(
            text=f"error: could not decode {path} as {encoding}: {exc}",
            ok=False,
        )
    except OSError as exc:
        return ToolResult(text=f"error: could not read {path}: {exc}", ok=False)
