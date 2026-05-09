# edit_file tool — replace one occurrence of old_text with new_text.
from pathlib import Path


SPEC = {
    "name": "edit_file",
    "description": (
        "Replace the first occurrence of old_text in a file with new_text. "
        "Fails if old_text is not present. Use this for targeted edits "
        "instead of overwriting the whole file with write_file."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or relative path to the file to edit.",
            },
            "old_text": {
                "type": "string",
                "description": "Exact text to find. Must appear in the file.",
            },
            "new_text": {
                "type": "string",
                "description": "Replacement text.",
            },
            "encoding": {
                "type": "string",
                "description": "Text encoding. Defaults to utf-8.",
            },
        },
        "required": ["path", "old_text", "new_text"],
    },
}


def edit_file(
    path: str,
    old_text: str,
    new_text: str,
    encoding: str = "utf-8",
) -> str:
    file_path = Path(path).expanduser()
    if not file_path.exists():
        return f"error: file not found: {path}"
    if not file_path.is_file():
        return f"error: not a regular file: {path}"
    try:
        contents = file_path.read_text(encoding=encoding)
    except (OSError, UnicodeDecodeError) as exc:
        return f"error: could not read {path}: {exc}"
    if old_text not in contents:
        return f"error: old_text not found in {path}"
    updated = contents.replace(old_text, new_text, 1)
    try:
        file_path.write_text(updated, encoding=encoding)
    except OSError as exc:
        return f"error: could not write {path}: {exc}"
    return f"edited {path}"
