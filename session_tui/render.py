"""Pure rendering primitives — Rich-renderable factories used by the App
and the per-event renderers. No widget access, no app state."""
from __future__ import annotations

from typing import Any

from rich.console import Group
from rich.padding import Padding
from rich.text import Text

from session_tui.style import BRAND, OK


def format_tool_input(tool_input: dict[str, Any]) -> str:
    if not tool_input:
        return ""
    parts: list[str] = []
    for k, v in tool_input.items():
        if isinstance(v, str) and len(v) > 80:
            v = v[:77] + "..."
        parts.append(f"{k}={v!r}")
    return ", ".join(parts)


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [{len(text) - limit} more chars elided]"


def truncate_lines(text: str, limit: int) -> str:
    """Truncate at the last full-line boundary <= limit. Used for diffs
    where mid-line truncation would corrupt the last hunk."""
    if len(text) <= limit:
        return text
    cut = text.rfind("\n", 0, limit)
    if cut == -1:
        cut = limit
    return text[:cut] + f"\n... [{len(text) - cut} more chars elided]"


def block(marker: str, marker_style: str, header: Text, body: Any | None = None) -> Group:
    """Claude Code-style block: a marker glyph + header line, optional
    2-space indented body."""
    head = Text()
    head.append(marker + "  ", style=marker_style)
    head.append_text(header)
    if body is None:
        return Group(head)
    return Group(head, Padding(body, (0, 0, 0, 3)))


def bar_line(head: Text, *, glyph: str, bar_style: str = BRAND) -> Text:
    """One-line tool-block row: `│ <glyph> <head>`. The `│` visually
    encapsulates the tool call so its result rows can hang underneath."""
    out = Text()
    out.append("│ ", style=bar_style)
    out.append(glyph + " ", style=bar_style)
    out.append_text(head)
    return out


def bar_block_body(
    text: str,
    *,
    glyph: str = "⎿",
    bar_style: str = BRAND,
    body_style: str = "dim",
) -> Text:
    """Multi-line tool-result body, each row prefixed by `│ ` so it
    visually belongs to the parent command. The first row gets `glyph`,
    every subsequent row gets a 2-space hanging indent under it."""
    lines = text.splitlines() or [""]
    out = Text()
    out.append("│ ", style=bar_style)
    out.append(glyph + " ", style=bar_style)
    out.append(lines[0], style=body_style)
    for line in lines[1:]:
        out.append("\n")
        out.append("│ ", style=bar_style)
        out.append("  " + line, style=body_style)
    return out


def looks_like_diff(text: str) -> bool:
    """Heuristic: a unified diff opens with `@@ `, `--- `, or `+++ `."""
    for line in text.splitlines():
        if not line.strip():
            continue
        return line.startswith("@@ ") or line.startswith("--- ") or line.startswith("+++ ")
    return False


def render_diff_block(text: str, *, bar_style: str = BRAND) -> Text:
    """Render a unified-diff string with git-style colors, framed by
    the same `│ ` bar as bar_block_body."""
    lines = text.splitlines() or [""]
    out = Text()
    for i, line in enumerate(lines):
        if i:
            out.append("\n")
        out.append("│ ", style=bar_style)
        out.append("⎿ " if i == 0 else "  ", style=bar_style)
        if line.startswith("@@ "):
            style = f"bold {BRAND}"
        elif line.startswith("+++ ") or line.startswith("--- "):
            style = "dim"
        elif line.startswith("+"):
            style = OK
        elif line.startswith("-"):
            style = "red"
        else:
            style = "dim"
        out.append(line, style=style)
    return out
