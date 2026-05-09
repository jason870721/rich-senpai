# write file tool
from pathlib import Path


SPEC = {
    "name": "write_file",
    "description": (
        "Create a new file or overwrite an existing one with the provided "
        "content. Parent directories must already exist. Returns a short "
        "confirmation string with the number of bytes written."
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


def write_file(path: str, content: str, encoding: str = "utf-8") -> str:
    file_path = Path(path)
    if not file_path.parent.exists():
        return f"error: parent directory does not exist: {file_path.parent}"
    try:
        bytes_written = file_path.write_text(content, encoding=encoding)
    except OSError as exc:
        return f"error: could not write {path}: {exc}"
    return f"wrote {bytes_written} bytes to {path}"
