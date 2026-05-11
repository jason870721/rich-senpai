# replace_in_file tool — find-and-replace a string in a file.
#
# Simpler than edit_file's unified diff: provide old_str (exact text to
# find) and new_str (replacement). The tool locates the first occurrence,
# replaces it, and returns a unified diff of the change for TUI rendering.
# Fails if old_str is not found or matches multiple locations.
from __future__ import annotations

from pathlib import Path

from rich_senpai.tools.file_access._diff import (
    apply_hunks,
    parse_hunks,
    DiffApplyError,
    DiffParseError,
)
from rich_senpai.tools.tool_result import ToolResult


SPEC = {
    "name": "replace_in_file",
    "description": (
        "Replace a string in a file with a new string. This is the "
        "simplest way to edit a file — provide the exact text to find "
        "(old_str) and what to replace it with (new_str). "
        "The tool replaces the first occurrence; include enough context "
        "in old_str to make it unique.\n"
        "\n"
        "Workflow: (1) call read_file to see the current content; "
        "(2) copy the exact text you want to replace as old_str; "
        "(3) provide the replacement as new_str.\n"
        "\n"
        "On success returns a unified diff of the change. "
        "Fails with a clear error if old_str is not found or matches "
        "multiple locations — when this happens, add more surrounding "
        "context to old_str to make it unique."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or relative path to the file to edit.",
            },
            "old_str": {
                "type": "string",
                "description": (
                    "Exact text to find and replace. Must match "
                    "byte-for-byte including whitespace. Include enough "
                    "surrounding context to make it unique."
                ),
            },
            "new_str": {
                "type": "string",
                "description": "The text to replace old_str with.",
            },
        },
        "required": ["path", "old_str", "new_str"],
    },
}


def _build_diff(path: str, old_str: str, new_str: str) -> str:
    """Build a unified diff from old→new replacement at line level."""
    old_lines = old_str.splitlines(keepends=True)
    new_lines = new_str.splitlines(keepends=True)

    # If no trailing newline in the strings, splitlines won't preserve it
    if old_str.endswith("\n") and not old_lines[-1].endswith("\n"):
        old_lines[-1] += "\n"
    if new_str.endswith("\n") and not new_lines[-1].endswith("\n"):
        new_lines[-1] += "\n"

    # Build the hunk header and body
    from difflib import unified_diff
    import io

    buf = io.StringIO()
    for line in unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=0,  # no context, we already have it in old_str/new_str
    ):
        buf.write(line)

    return buf.getvalue()


def replace_in_file(
    path: str,
    old_str: str,
    new_str: str,
) -> ToolResult:
    file_path = Path(path).expanduser()
    if not file_path.exists():
        return ToolResult(text=f"error: file not found: {path}", ok=False)
    if not file_path.is_file():
        return ToolResult(text=f"error: not a regular file: {path}", ok=False)

    try:
        contents = file_path.read_text()
    except (OSError, UnicodeDecodeError) as exc:
        return ToolResult(text=f"error: could not read {path}: {exc}", ok=False)

    # Count occurrences
    count = contents.count(old_str)
    if count == 0:
        return ToolResult(
            text=(
                f"error: old_str not found in {path}. "
                f"The text you provided does not exist in the file. "
                f"Use read_file to check the current content, then "
                f"copy the exact text you want to replace."
            ),
            ok=False,
        )
    if count > 1:
        return ToolResult(
            text=(
                f"error: old_str matches {count} locations in {path}. "
                f"Add more surrounding context to old_str to make it "
                f"unique — include a few more lines above or below the "
                f"target area."
            ),
            ok=False,
        )

    # Replace
    updated = contents.replace(old_str, new_str, 1)

    # Build a diff for TUI rendering
    diff = _build_diff(path, old_str, new_str)

    try:
        file_path.write_text(updated)
    except OSError as exc:
        return ToolResult(text=f"error: could not write {path}: {exc}", ok=False)

    return ToolResult(text=diff)
