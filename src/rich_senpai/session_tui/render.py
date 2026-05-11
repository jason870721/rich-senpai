"""Pure rendering primitives — Rich-renderable factories used by the App
and the per-event renderers. No widget access, no app state."""
from __future__ import annotations

from typing import Any, Mapping

from rich.console import Group
from rich.padding import Padding
from rich.text import Text

from rich_senpai.session_tui.style import BRAND, OK


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
    """Heuristic: a unified diff opens with `@@ `, `--- `, or `+++ `.

    Leading `#`-prefixed annotation lines (e.g. ``# replaced 4
    occurrences`` from edit_file's replace_all path) are skipped so the
    diff is still detected and rendered with colors.
    """
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.startswith("#"):
            continue
        return line.startswith("@@ ") or line.startswith("--- ") or line.startswith("+++ ")
    return False


def format_uptime(seconds: float) -> str:
    """``0d 1h 24m`` — coarse-resolution session-uptime formatter."""
    seconds = max(0.0, seconds)
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{days}d {hours}h {minutes}m"


def format_input_stats(
    *,
    model_label: str,
    in_tokens: int,
    out_tokens: int,
    iters: int,
    uptime_seconds: float,
) -> Text:
    """Render the stats line beneath the input dock: model · tokens · iter · uptime."""
    return Text.assemble(
        (model_label, f"bold {BRAND}"),
        ("   ·   ", "dim"),
        ("in ", "dim"),
        (f"{in_tokens:,}", BRAND),
        ("   ", "dim"),
        ("out ", "dim"),
        (f"{out_tokens:,} tok", BRAND),
        ("   ·   ", "dim"),
        ("iter ", "dim"),
        (f"{iters}", BRAND),
        ("   ·   ", "dim"),
        ("up ", "dim"),
        (format_uptime(uptime_seconds), BRAND),
    )


def format_status_line(
    *,
    spinner_frame: str,
    label: str,
    iteration: int,
    elapsed_seconds: float,
    model_label: str,
) -> Text:
    """Render the busy-spinner row shown while a turn is in flight."""
    return Text.assemble(
        (f"{spinner_frame}  ", f"bold {BRAND}"),
        (label, BRAND),
        (f"   iter {iteration}", "dim"),
        (f"   {elapsed_seconds:4.1f}s", "dim"),
        (f"   {model_label}", "dim"),
        ("   esc to interrupt", "dim"),
    )


def format_user_echo(text: str) -> Text:
    """User-typed input echoed into the log right before the agent's turn starts."""
    out = Text()
    out.append("▎ ", style=f"bold {BRAND}")
    out.append("> ", style=f"bold {BRAND}")
    out.append(text, style="bold white")
    return out


def format_turn_footer(
    *,
    turn_no: int,
    stop_reason: str,
    iterations: int,
    usage: Mapping[str, int] | None,
    model_label: str,
    active_skills: set[str],
) -> Text:
    """One-line summary written at the end of every turn."""
    usage = usage or {}
    skill_suffix = (
        f"   skills · {', '.join(sorted(active_skills))}" if active_skills else ""
    )
    return Text.assemble(
        ("\n  ── ", "dim"),
        (f"#{turn_no}  ", f"bold {BRAND}"),
        #(f"stop={stop_reason}", "dim"),
        (f" iters {iterations}", "dim"),
        (
            f"   token (in:{usage.get('input_tokens', 0)}/out:{usage.get('output_tokens', 0)})",
            "dim",
        ),
        (skill_suffix, "dim"),
    )


def render_diff_block(text: str, *, bar_style: str = BRAND) -> Text:
    """Render a unified-diff string with git-style colors, framed by
    the same `│ ` bar as bar_block_body.

    `#`-prefixed annotation lines (e.g. ``# replaced 4 occurrences``)
    render in italic BRAND so they stand out as metadata above the diff
    body without being mistaken for added/removed content.
    """
    lines = text.splitlines() or [""]
    out = Text()
    for i, line in enumerate(lines):
        if i:
            out.append("\n")
        out.append("│ ", style=bar_style)
        out.append("⎿ " if i == 0 else "  ", style=bar_style)
        if line.startswith("#"):
            style = f"italic {BRAND}"
        elif line.startswith("@@ "):
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
