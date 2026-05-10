# edit_file tool — apply a unified diff to a file.
#
# Input is one or more hunks (no `---`/`+++` file headers required). The
# applier verifies each context/removal line matches the file byte-for-
# byte; on mismatch it returns a targeted error so the agent can re-read
# and rebuild the hunk against the current line numbers.
from pathlib import Path

from tools._diff import (
    DiffApplyError,
    DiffParseError,
    apply_hunks,
    parse_hunks,
)
from tools.tool_result import ToolResult


SPEC = {
    "name": "edit_file",
    "description": (
        "Apply a unified diff to a file. Workflow: (1) call read_file to "
        "capture exact line numbers and surrounding context; (2) author a "
        "unified diff with one or more hunks; (3) call edit_file with "
        "{path, diff}.\n"
        "\n"
        "Diff format: each hunk starts with a header `@@ -start,len "
        "+start,len @@` followed by body lines, each beginning with one "
        "of:\n"
        "  ` ` (space) — unchanged context line\n"
        "  `-`         — line to remove\n"
        "  `+`         — line to add\n"
        "Include 3 lines of unchanged context before and after every "
        "change. For multiple regions in the same file, emit multiple "
        "`@@` hunks in a single diff string — do NOT skip lines within a "
        "hunk.\n"
        "\n"
        "The header `,len` counts are advisory — the parser auto-"
        "recounts from the body (like `git apply --recount`), so "
        "miscounting by one or two is harmless. What MUST be exact: "
        "every ` ` (context) and `-` (remove) line has to match the "
        "file byte-for-byte, including leading whitespace.\n"
        "\n"
        "Do NOT include `---`/`+++` file headers (they are tolerated but "
        "ignored). Do NOT include the `<n>\\t` line-number prefix from "
        "read_file output — only the raw line content goes into the diff "
        "body. Tabs vs spaces matter — a single mismatch fails the patch.\n"
        "\n"
        "On apply failure, the file has shifted under you (or your "
        "context lines are wrong): re-read the file and rebuild the hunk "
        "rather than retrying the same diff. On success, edit_file "
        "returns the applied diff so the TUI can render it in git-diff "
        "style."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or relative path to the file to edit.",
            },
            "diff": {
                "type": "string",
                "description": (
                    "Unified diff body — one or more `@@` hunks, body lines "
                    "prefixed with ' ', '-', or '+'. No `---`/`+++` headers."
                ),
            },
            "encoding": {
                "type": "string",
                "description": "Text encoding. Defaults to utf-8.",
            },
        },
        "required": ["path", "diff"],
    },
}


def _format_applied_diff(path: str, diff: str) -> str:
    """Return the diff with synthesized `--- a/<path>` / `+++ b/<path>`
    headers (if not already present) so downstream renderers (the TUI)
    can treat every diff result uniformly."""
    stripped = diff.lstrip("\n")
    if stripped.startswith("--- "):
        return diff if diff.endswith("\n") else diff + "\n"
    header = f"--- a/{path}\n+++ b/{path}\n"
    body = stripped if stripped.endswith("\n") else stripped + "\n"
    return header + body


def edit_file(
    path: str,
    diff: str,
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

    try:
        hunks = parse_hunks(diff)
    except DiffParseError as exc:
        return ToolResult(text=f"error: diff parse failed: {exc}", ok=False)

    try:
        updated = apply_hunks(contents, hunks)
    except DiffApplyError as exc:
        return ToolResult(text=f"error: diff apply failed: {exc}", ok=False)

    try:
        file_path.write_text(updated, encoding=encoding)
    except OSError as exc:
        return ToolResult(text=f"error: could not write {path}: {exc}", ok=False)

    return ToolResult(text=_format_applied_diff(path, diff))
