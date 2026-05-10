# write file tool
from pathlib import Path

from tools.tool_result import ToolResult


SPEC = {
    "name": "write_file",
    "description": (
        "Create a new file or overwrite an existing one with the provided "
        "content. Any missing parent directories are created automatically. "
        "Returns a short confirmation string with the number of bytes written."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or relative path to the file to write.",
            },
            "content": {
                "type": "string",
                "description": "Full text content to write to the file.",
            },
            "encoding": {
                "type": "string",
                "description": "Text encoding to write with. Defaults to utf-8.",
            },
        },
        "required": ["path", "content"],
    },
}


def write_file(path: str, content: str, encoding: str = "utf-8") -> ToolResult:
    file_path = Path(path).expanduser()
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        bytes_written = file_path.write_text(content, encoding=encoding)
    except OSError as exc:
        return ToolResult(text=f"error: could not write {path}: {exc}", ok=False)
    return ToolResult(text=f"wrote {bytes_written} bytes to {path}")
