# grep tool — recursively scan a directory for a regex pattern.
#
# Pure-Python so it works on any platform without depending on `rg`/`grep`
# being installed. Two output modes:
#
#   mode="content" (default) — `path:lineno:matching line` per hit
#   mode="files"             — one matching path per line (deduped)
#
# Skips noisy directories by default (.git, __pycache__, node_modules,
# venv, .venv, dist, build) so the agent doesn't drown in third-party hits.
# An optional `glob` filter (e.g. "*.py") restricts which files are read,
# and `max_results` caps output so a hot pattern can't blow the context
# window.
from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from rich_senpai.tools.tool_result import ToolResult


SPEC = {
    "name": "grep",
    "description": (
        "Recursively search a directory for a regular-expression pattern "
        "and return matching lines (or matching file paths). Use this to "
        "locate a symbol, string, or definition across the codebase before "
        "reading or editing files. Output is line-oriented:\n"
        "  mode='content' (default) — `path:lineno:line` for every hit\n"
        "  mode='files'             — one matching file path per line\n"
        "Pattern is a Python regex (re module). Common skip dirs (.git, "
        "__pycache__, node_modules, venv, .venv, dist, build) and binary "
        "files are excluded automatically. Restrict the search with `glob` "
        "(e.g. '*.py', '*.md') and cap output with `max_results` (default "
        "200). Prefer this over a `bash` grep call — output is already "
        "trimmed for the model's context."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Python regex to match against each line.",
            },
            "path": {
                "type": "string",
                "description": (
                    "File or directory to search. Defaults to the current "
                    "working directory."
                ),
            },
            "glob": {
                "type": "string",
                "description": (
                    "Filename glob filter (e.g. '*.py', '*.md'). Applied to "
                    "the basename only. Defaults to all files."
                ),
            },
            "mode": {
                "type": "string",
                "enum": ["content", "files"],
                "description": (
                    "'content' returns `path:lineno:line` for each hit; "
                    "'files' returns one matching path per line. Defaults "
                    "to 'content'."
                ),
            },
            "case_insensitive": {
                "type": "boolean",
                "description": "Case-insensitive match. Defaults to false.",
            },
            "max_results": {
                "type": "integer",
                "description": (
                    "Maximum lines of output. Defaults to 200. The result "
                    "is annotated with `... (truncated)` if the cap was "
                    "reached so the agent can refine the query."
                ),
            },
        },
        "required": ["pattern"],
    },
}


_SKIP_DIRS = frozenset({
    ".git",
    "__pycache__",
    "node_modules",
    "venv",
    ".venv",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".idea",
    ".vscode",
})

_DEFAULT_MAX_RESULTS = 200
# Files larger than this are skipped — likely binary/data, would dominate
# the result if matched, and aren't useful for code navigation.
_MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MiB


def _looks_binary(chunk: bytes) -> bool:
    """Heuristic: a NUL byte in the first read implies binary."""
    return b"\x00" in chunk


def _iter_candidate_files(root: Path, glob: str | None):
    """Yield candidate file paths under `root`, skipping noise dirs."""
    if root.is_file():
        if glob is None or fnmatch.fnmatch(root.name, glob):
            yield root
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if glob is not None and not fnmatch.fnmatch(name, glob):
                continue
            yield Path(dirpath) / name


def grep(
    pattern: str,
    path: str | None = None,
    glob: str | None = None,
    mode: str = "content",
    case_insensitive: bool = False,
    max_results: int = _DEFAULT_MAX_RESULTS,
) -> ToolResult:
    if mode not in ("content", "files"):
        return ToolResult(
            text=f"error: invalid mode '{mode}' (expected 'content' or 'files')",
            ok=False,
        )
    try:
        flags = re.IGNORECASE if case_insensitive else 0
        regex = re.compile(pattern, flags)
    except re.error as exc:
        return ToolResult(text=f"error: invalid regex: {exc}", ok=False)

    root = Path(path).expanduser() if path else Path.cwd()
    if not root.exists():
        return ToolResult(text=f"error: path not found: {root}", ok=False)

    if max_results <= 0:
        max_results = _DEFAULT_MAX_RESULTS

    hits: list[str] = []
    truncated = False

    for file_path in _iter_candidate_files(root, glob):
        try:
            if file_path.stat().st_size > _MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        try:
            with file_path.open("rb") as fh:
                head = fh.read(2048)
                if _looks_binary(head):
                    continue
                rest = fh.read()
        except OSError:
            continue
        try:
            text = (head + rest).decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = (head + rest).decode("latin-1")
            except UnicodeDecodeError:
                continue

        rel = file_path.as_posix()
        matched_in_file = False
        for lineno, line in enumerate(text.splitlines(), start=1):
            if regex.search(line) is None:
                continue
            if mode == "files":
                hits.append(rel)
                matched_in_file = True
                break
            hits.append(f"{rel}:{lineno}:{line.rstrip()}")
            if len(hits) >= max_results:
                truncated = True
                break
        if truncated:
            break
        if mode == "files" and matched_in_file and len(hits) >= max_results:
            truncated = True
            break

    if not hits:
        return ToolResult(text=f"no matches for /{pattern}/ under {root.as_posix()}")

    body = "\n".join(hits)
    if truncated:
        body += f"\n... (truncated at {max_results} results — refine pattern or narrow path/glob)"
    return ToolResult(text=body)
