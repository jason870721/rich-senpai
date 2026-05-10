# read file tool — line-numbered output (cat -n style).
#
# Each line is prefixed with `<n>\t` where `<n>` is right-aligned in 6
# columns. The agent uses these line numbers to author edit_file diff
# hunks; the prefix is metadata and MUST NOT be included in any diff body.
from pathlib import Path

from tools.tool_result import ToolResult


SPEC = {
    "name": "read_file",
    "description": (
        "Read the contents of a local text file and return it with line "
        "numbers (cat -n style). Each output line is `<n>\\t<content>` "
        "where <n> is the 1-indexed line number. The `<n>\\t` prefix is "
        "metadata for navigating the file and authoring edit_file diffs — "
        "it MUST be stripped before constructing any unified-diff body."
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


def _format_with_line_numbers(text: str) -> str:
    if text == "":
        return ""
    trailing_nl = text.endswith("\n")
    lines = text.split("\n")
    if trailing_nl:
        lines.pop()
    formatted = "\n".join(f"{i + 1:>6}\t{line}" for i, line in enumerate(lines))
    return formatted + ("\n" if trailing_nl else "")


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
    return ToolResult(text=_format_with_line_numbers(contents))
