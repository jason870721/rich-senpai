# edit_file tool — replace one occurrence of old_text with new_text.
from pathlib import Path

from tools.tool_result import ToolResult


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
) -> ToolResult:
    file_path = Path(path).expanduser()
    if not file_path.exists():
        return ToolResult(text=f"error: file not found: {path}", ok=False)
    if not file_path.is_file():
        return ToolResult(text=f"error: not a regular file: {path}", ok=False)
    try:
        contents = file_path.read_text(encoding=encoding)
    except (OSError, UnicodeDecodeError) as exc:
        return ToolResult(text=f"error: could not read {path}: {exc}", ok=False)
    if old_text not in contents:
        return ToolResult(text=f"error: old_text not found in {path}", ok=False)
    updated = contents.replace(old_text, new_text, 1)
    try:
        file_path.write_text(updated, encoding=encoding)
    except OSError as exc:
        return ToolResult(text=f"error: could not write {path}: {exc}", ok=False)
    return ToolResult(text=f"edited {path}")
