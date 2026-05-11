"""Per-event renderers for agent events.

Each renderer takes ``(app, event)`` and writes Rich renderables into the
log via ``app.write``. ``EVENT_RENDERERS`` is the dispatch table; adding a
new event kind = write a renderer + register it here.

Event kinds we handle:

  - ``assistant_text``     — model's user-facing reply chunk
  - ``tool_use``           — agent invoked a tool
  - ``tool_result``        — tool returned a result (or error)
  - ``wait``               — wait tool slept
  - ``compact``            — context compaction fired
  - ``background_drain``   — background notifications drained
  - ``inbox_drain``        — agent inbox drained
  - ``interrupted``        — user pressed Esc

`render_skill_load` is exported separately because `tool_use` calls it as
a special case (load_skill gets its own banner instead of the generic
tool_use line).
"""
from __future__ import annotations

from typing import Any, Callable, TYPE_CHECKING

from rich.text import Text

from core import state
from session_tui.render import (
    bar_block_body,
    bar_line,
    block,
    format_tool_input,
    looks_like_diff,
    render_diff_block,
    truncate,
    truncate_lines,
)
from session_tui.style import BRAND, GOLD, TOOL_RESULT_PREVIEW_CHARS, TOOL_USE


if TYPE_CHECKING:
    from session_tui.tui import SenpaiApp


# ---------------------------------------------------------------------------
# Per-event renderers
# ---------------------------------------------------------------------------


def render_assistant_text(app: "SenpaiApp", event: dict[str, Any]) -> None:
    """Hand the agent's text reply off to the App's typewriter reveal.

    The App owns the `#streaming` widget where the partial text lives
    during the per-character reveal, and commits the final Markdown
    block to the log once the reveal completes. Other event renderers
    (tool_use, tool_result, …) keep writing to the log directly — only
    assistant_text takes this animated path."""
    text = event["text"].strip()
    if not text:
        return
    app.start_streaming(text, event.get("iteration", 0))


def render_tool_use(app: "SenpaiApp", event: dict[str, Any]) -> None:
    name = event.get("name")
    # Special-cased tools have their own surface in the UI; suppress
    # both the tool_use line in the log and the matching tool_result.
    if name == "load_skill":
        render_skill_load(app, event)
        app.suppress_tool_id(event.get("id"))
        return
    if name == "TodoWrite":
        # The bottom panel is the canonical view, so always suppress
        # the JSON-blob result body. We only render the tool_use header
        # on the first call per round as a one-line "todos are being
        # managed" announcement.
        app.suppress_tool_id(event.get("id"))
        if app.todos_panel.tool_use_logged:
            return
        app.todos_panel.tool_use_logged = True
        # Fall through to render the standard tool_use header line.

    args = format_tool_input(event.get("input") or {})
    head = Text()
    head.append(name or "?", style=f"bold {TOOL_USE}")
    head.append("(", style="dim")
    head.append(args, style="dim")
    head.append(")", style="dim")
    head.append(f"   iter {event.get('iteration', 0)}", style="dim")
    app.write(Text(""))
    app.write(bar_line(head, glyph="⏺", bar_style=BRAND))


def render_tool_result(app: "SenpaiApp", event: dict[str, Any]) -> None:
    tu_id = event.get("id")
    if app.consume_suppressed(tu_id):
        if event.get("name") == "TodoWrite":
            app.todos_panel.refresh(app)
        return
    ok = event.get("ok", True)
    raw = event["output"]
    if ok and looks_like_diff(raw):
        output = truncate_lines(raw, TOOL_RESULT_PREVIEW_CHARS)
        app.write(render_diff_block(output, bar_style=BRAND))
        return
    output = truncate(raw, TOOL_RESULT_PREVIEW_CHARS)
    # ok defaults to True for older / non-bash tools that haven't been
    # taught to surface failure. Red is reserved for actual errors.
    if ok:
        bar_style, body_style = BRAND, "dim"
    else:
        bar_style, body_style = "red", "red"
    app.write(bar_block_body(output, glyph="⎿", bar_style=bar_style, body_style=body_style))


def render_wait(app: "SenpaiApp", event: dict[str, Any]) -> None:
    app.write(
        Text.assemble(
            ("⏸  ", GOLD),
            ("wait", f"bold {GOLD}"),
            (f"   iter {event.get('iteration', 0)} — sleeping {event.get('seconds', '?')}s", "dim"),
        )
    )


def render_compact(app: "SenpaiApp", event: dict[str, Any]) -> None:
    app.write(
        Text.assemble(
            ("⌁  ", GOLD),
            ("compact", f"bold {GOLD}"),
            (f"   {event.get('reason', '')}", "dim"),
        )
    )


def render_background_drain(app: "SenpaiApp", event: dict[str, Any]) -> None:
    n = len(event.get("notifications", []))
    app.write(
        Text.assemble(
            ("◇  ", GOLD),
            ("background", f"bold {GOLD}"),
            (f"   {n} notification(s) drained", "dim"),
        )
    )


def render_inbox_drain(app: "SenpaiApp", event: dict[str, Any]) -> None:
    n = len(event.get("messages", []))
    app.write(
        Text.assemble(
            ("✉  ", GOLD),
            ("inbox", f"bold {GOLD}"),
            (f"   {n} message(s) drained", "dim"),
        )
    )


def render_interrupted(app: "SenpaiApp", event: dict[str, Any]) -> None:
    stage = event.get("stage", "")
    suffix = f"   {stage}" if stage else ""
    app.write(
        Text.assemble(
            ("⏼  ", GOLD),
            ("interrupted", f"bold {GOLD}"),
            (f"   iter {event.get('iteration', 0)}{suffix}", "dim"),
        )
    )


def render_skill_load(app: "SenpaiApp", event: dict[str, Any]) -> None:
    """Show a clear banner when the agent loads a skill, and remember
    which skills have been activated so the turn footer can list them."""
    name = (event.get("input") or {}).get("name") or "<unknown>"

    skill = state.SKILLS.skills.get(name)
    if skill:
        app.active_skills.add(name)
        description = str(skill.get("description", {})).strip() or "(no description)"
        available = True
    else:
        description = (
            "skill not found — agent will get an error result. "
            f"Available: {', '.join(sorted(state.SKILLS.skills.keys())) or '(none)'}"
        )
        available = False

    accent = GOLD if available else "red"
    glyph = "📚" if available else "❓"
    label = "skill loaded" if available else "skill NOT FOUND"
    header = Text()
    header.append(label, style=f"bold {accent}")
    header.append("   ")
    header.append(name, style="bold")
    body = Text(description, style="dim")
    app.write(block(glyph, accent, header, body))


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

EVENT_RENDERERS: dict[str, Callable[["SenpaiApp", dict[str, Any]], None]] = {
    "assistant_text": render_assistant_text,
    "tool_use": render_tool_use,
    "tool_result": render_tool_result,
    "wait": render_wait,
    "compact": render_compact,
    "background_drain": render_background_drain,
    "inbox_drain": render_inbox_drain,
    "interrupted": render_interrupted,
}


def status_label_for(event: dict[str, Any]) -> str:
    """Map an event to the spinner label shown in the busy line."""
    kind = event.get("type")
    if kind == "llm_request":
        return "thinking…"
    if kind == "llm_response":
        # transient — typically immediately followed by tool_use /
        # assistant_text which overwrite this anyway
        return "model replied"
    if kind == "tool_use":
        return f"calling {event.get('name', 'tool')}…"
    if kind == "tool_result":
        return "got tool result"
    if kind == "assistant_text":
        return "writing reply…"
    if kind == "compact":
        return "compacting context…"
    if kind == "background_drain":
        return "draining background notifications"
    if kind == "inbox_drain":
        return "draining inbox"
    if kind == "wait":
        seconds = event.get("seconds", "?")
        return f"sleeping {seconds}s…"
    if kind == "interrupted":
        return "stopping…"
    return "thinking"


def render_event(app: "SenpaiApp", event: dict[str, Any]) -> None:
    """Top-level dispatch: pick a renderer by event type."""
    renderer = EVENT_RENDERERS.get(event.get("type"))
    if renderer is not None:
        renderer(app, event)
