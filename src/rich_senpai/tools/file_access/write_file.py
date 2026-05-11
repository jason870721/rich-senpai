# write file tool — overwrite or create.
#
# When creating a new file, the result text is a synthetic unified diff
# (`--- /dev/null` -> `+++ b/<path>`) so the TUI renders the creation in
# git-diff style alongside edit_file's output. When overwriting an
# existing file, returns the byte-count confirmation (no diff — we don't
# read the prior content; in-place changes should use edit_file anyway).
from rich_senpai.tools.file_access._diff import render_new_file_diff
from rich_senpai.tools.file_access._guard import PathOutsideWorkdirError, resolve_safe
from rich_senpai.tools.tool_result import ToolResult


SPEC = {
    "name": "write_file",
    "description": (
        "Create a new file or overwrite an existing one with the provided "
        "content. Any missing parent directories are created automatically. "
        "On a new-file create the result is a unified diff against "
        "/dev/null (so the TUI can render it in git-diff style); on an "
        "overwrite of an existing file the result is a byte-count "
        "confirmation. For in-place edits to an existing file, prefer "
        "edit_file — it preserves surrounding content. Access outside "
        "the workdir is denied unless allow_outside_workdir is set to "
        "true."
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
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        bytes_written = file_path.write_text(content, encoding=encoding)
    except OSError as exc:
        return ToolResult(text=f"error: could not write {path}: {exc}", ok=False)

    if not existed_before:
        return ToolResult(text=render_new_file_diff(path, content))
    return ToolResult(text=f"wrote {bytes_written} bytes to {path}")
