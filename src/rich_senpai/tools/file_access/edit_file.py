# edit_file tool — exact substring replace, Claude Code style.
#
# No diff parsing. The agent supplies old_string + new_string and the
# tool either finds the substring exactly once and replaces it, or
# fails with guidance. `replace_all=True` performs every replacement.
#
# Guard: the agent must have called read_file on this path earlier in
# the same session (tracked via _session.ReadTracker). When no tracker
# is installed (direct tests/scripts), this guard is skipped so callers
# don't need harness setup.
from __future__ import annotations

import io
from difflib import unified_diff

from rich_senpai.tools.file_access._guard import PathOutsideWorkdirError, resolve_safe
from rich_senpai.tools.file_access._session import get_tracker
from rich_senpai.tools.tool_result import ToolResult


SPEC = {
    "name": "edit_file",
    "description": (
        "Performs an exact string replacement in an existing file.\n"
        "\n"
        "Workflow: (1) call read_file on the target file first — required, "
        "the tool refuses to edit a file you haven't loaded into context; "
        "(2) copy the exact text to replace as old_string (byte-for-byte, "
        "tabs vs spaces matter, and DO NOT include the `<n>\\t` line-number "
        "prefix from read_file output); (3) supply the replacement as "
        "new_string.\n"
        "\n"
        "By default old_string must occur exactly once in the file — if it "
        "appears 0 times the tool errors and you should re-read the file; "
        "if it appears multiple times the tool errors and you should "
        "include more surrounding context to make it unique. Pass "
        "replace_all=true to replace every occurrence at once (useful for "
        "renaming a variable across the whole file).\n"
        "\n"
        "old_string and new_string MUST differ. To create a new file or "
        "fully overwrite one, use write_file instead. On success the tool "
        "returns a unified diff so the TUI can render the change. Access "
        "outside the workdir is denied unless allow_outside_workdir is set "
        "to true."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or relative path to the file to edit.",
            },
            "old_string": {
                "type": "string",
                "description": (
                    "Exact text to find. Must match byte-for-byte including "
                    "whitespace and newlines. Include enough surrounding "
                    "context to make it unique unless replace_all is true."
                ),
            },
            "new_string": {
                "type": "string",
                "description": (
                    "Replacement text. Must differ from old_string."
                ),
            },
            "replace_all": {
                "type": "boolean",
                "description": (
                    "Replace every occurrence of old_string. Defaults to "
                    "false (require a unique match)."
                ),
            },
            "encoding": {
                "type": "string",
                "description": "Text encoding. Defaults to utf-8.",
            },
            "allow_outside_workdir": {
                "type": "boolean",
                "description": (
                    "Allow editing files outside the project workdir. "
                    "Defaults to false."
                ),
            },
        },
        "required": ["path", "old_string", "new_string"],
    },
}


def _build_diff(path: str, old_str: str, new_str: str) -> str:
    """Build a unified diff from old→new replacement at line level."""
    old_lines = old_str.splitlines(keepends=True)
    new_lines = new_str.splitlines(keepends=True)

    if old_lines and old_str.endswith("\n") and not old_lines[-1].endswith("\n"):
        old_lines[-1] += "\n"
    if new_lines and new_str.endswith("\n") and not new_lines[-1].endswith("\n"):
        new_lines[-1] += "\n"

    buf = io.StringIO()
    for line in unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=0,
    ):
        buf.write(line)
    return buf.getvalue()


def edit_file(
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
    encoding: str = "utf-8",
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

    tracker = get_tracker()
    if tracker is not None and not tracker.was_read(file_path):
        return ToolResult(
            text=(
                f"error: you must use read_file on {path} before editing it. "
                f"Read the file first so your old_string matches the current "
                f"content exactly."
            ),
            ok=False,
        )

    if old_string == new_string:
        return ToolResult(
            text="error: old_string and new_string are identical — no edit to apply.",
            ok=False,
        )

    try:
        contents = file_path.read_text(encoding=encoding)
    except (OSError, UnicodeDecodeError) as exc:
        return ToolResult(text=f"error: could not read {path}: {exc}", ok=False)

    count = contents.count(old_string)
    if count == 0:
        return ToolResult(
            text=(
                f"error: old_string not found in {path}. "
                f"The text you provided does not appear in the file. "
                f"Re-read the file and copy the exact text — including "
                f"whitespace — that you want to replace."
            ),
            ok=False,
        )
    if count > 1 and not replace_all:
        return ToolResult(
            text=(
                f"error: old_string matches {count} locations in {path}. "
                f"Either include more surrounding context in old_string to "
                f"make it unique, or set replace_all=true to replace every "
                f"occurrence."
            ),
            ok=False,
        )

    if replace_all:
        updated = contents.replace(old_string, new_string)
    else:
        updated = contents.replace(old_string, new_string, 1)

    try:
        file_path.write_text(updated, encoding=encoding)
    except OSError as exc:
        return ToolResult(text=f"error: could not write {path}: {exc}", ok=False)

    if tracker is not None:
        tracker.mark_read(file_path)

    diff = _build_diff(path, old_string, new_string)
    if replace_all and count > 1:
        diff = f"# replaced {count} occurrences\n{diff}"
    return ToolResult(text=diff)
