# read file tool
from pathlib import Path


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


def read_file(path: str, encoding: str = "utf-8") -> str:
    file_path = Path(path)
    if not file_path.exists():
        return f"error: file not found: {path}"
    if not file_path.is_file():
        return f"error: not a regular file: {path}"
    try:
        return file_path.read_text(encoding=encoding)
    except UnicodeDecodeError as exc:
        return f"error: could not decode {path} as {encoding}: {exc}"
    except OSError as exc:
        return f"error: could not read {path}: {exc}"
