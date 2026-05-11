# write_file tool — create or overwrite.
#
# New files: returns a synthetic unified diff against /dev/null so the
# TUI can render the creation in git-diff style.
# Overwriting an existing file is gated by the session ReadTracker —
# the agent must have called read_file first, mirroring Claude Code's
# Write tool. New-file creates skip the check (file doesn't exist yet).
from rich_senpai.tools.file_access._guard import PathOutsideWorkdirError, resolve_safe
from rich_senpai.tools.file_access._session import get_tracker
from rich_senpai.tools.tool_result import ToolResult


SPEC = {
    "name": "write_file",
    "description": (
        "Writes a file to the local filesystem. Use this for creating new "
        "files or fully overwriting an existing one. For partial edits to "
        "an existing file, prefer edit_file — it preserves surrounding "
        "content and is harder to misuse.\n"
        "\n"
        "Overwriting an existing file requires you to have called "
        "read_file on it first in this session — the tool refuses to "
        "blindly clobber a file you haven't loaded into context. New "
        "files (path doesn't exist) need no prior read. Missing parent "
        "directories are created automatically.\n"
        "\n"
        "On a new-file create the result is a unified diff against "
        "/dev/null (so the TUI can render it in git-diff style); on an "
        "overwrite the result is a byte-count confirmation. Access "
        "outside the workdir is denied unless allow_outside_workdir is "
        "set to true."
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
            "allow_outside_workdir": {
                "type": "boolean",
                "description": (
                    "Allow writing files outside the project workdir. "
                    "Defaults to false — the tool will refuse to write to "
                    "/etc/passwd, ~/.ssh, etc."
                ),
            },
        },
        "required": ["path", "content"],
    },
}


def _render_new_file_diff(path: str, content: str) -> str:
    """Synthesize a unified diff for a brand-new file (`/dev/null` → path)."""
    if content == "":
        return f"--- /dev/null\n+++ b/{path}\n"
    trailing_nl = content.endswith("\n")
    raw = content.split("\n")
    lines = raw[:-1] if trailing_nl else raw
    n = len(lines)
    header = f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{n} @@\n"
    body = "".join(f"+{line}\n" for line in lines)
    if not trailing_nl:
        body += "\\ No newline at end of file\n"
    return header + body


def write_file(
    path: str,
    content: str,
    encoding: str = "utf-8",
    allow_outside_workdir: bool = False,
) -> ToolResult:
    try:
        file_path = resolve_safe(path, allow_outside_workdir=allow_outside_workdir)
    except PathOutsideWorkdirError as exc:
        return ToolResult(text=f"error: {exc}", ok=False)

    existed_before = file_path.exists()

    tracker = get_tracker()
    if existed_before and tracker is not None and not tracker.was_read(file_path):
        return ToolResult(
            text=(
                f"error: you must use read_file on {path} before "
                f"overwriting it. Read the file first so you don't blindly "
                f"clobber existing content; if you want a partial change "
                f"use edit_file instead."
            ),
            ok=False,
        )

    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        bytes_written = file_path.write_text(content, encoding=encoding)
    except OSError as exc:
        return ToolResult(text=f"error: could not write {path}: {exc}", ok=False)

    if tracker is not None:
        tracker.mark_read(file_path)

    if not existed_before:
        return ToolResult(text=_render_new_file_diff(path, content))
    return ToolResult(text=f"wrote {bytes_written} bytes to {path}")
