"""Concrete LivePanel subclasses — todos and background tasks.

Each panel keeps its own glyph / accent / item formatting so the visual
design is preserved exactly as it was before the LivePanel refactor; only
the lifecycle (snapshot → signature → settle? → archive / hide) is shared.
"""
from __future__ import annotations

from rich.text import Text

from core import state
from session_tui.live_panel import LivePanel
from session_tui.style import BRAND, GOLD, OK


# ---------------------------------------------------------------------------
# Todos
# ---------------------------------------------------------------------------

_TODO_GLYPHS = {"completed": "✓", "in_progress": "▸", "pending": "○"}
_TODO_STYLES = {
    "completed": f"dim {OK}",
    "in_progress": f"bold {GOLD}",
    "pending": "white",
}


class TodosPanel(LivePanel[dict]):
    """In-process todo checklist managed by the TodoWrite tool."""

    def __init__(self) -> None:
        super().__init__(
            widget_id="todos",
            glyph="✦",
            accent=BRAND,
            title="todos",
            done_accent=OK,
        )
        # TodoWrite is loud — its tool_use fires every time the agent
        # tweaks the list. We log the tool_use header only on the first
        # call per "round" so the user sees that todos are being managed,
        # then defer to this docked panel for the live view. The flag is
        # reset to False whenever an all-done snapshot is archived, so
        # the next round (a fresh, incomplete list) re-announces.
        self.tool_use_logged = False

    def snapshot(self) -> list[dict]:
        return state.TODO.items

    def signature(self, items: list[dict]) -> tuple:
        return tuple((t["content"], t["status"]) for t in items)

    def all_settled(self, items: list[dict]) -> bool:
        return all(t["status"] == "completed" for t in items)

    def build_body(self, items: list[dict]) -> Text:
        body = Text()
        for i, item in enumerate(items):
            status = item["status"]
            mark = _TODO_GLYPHS.get(status, "?")
            label = item["activeForm"] if status == "in_progress" else item["content"]
            if i:
                body.append("\n")
            body.append(f"{mark}  {label}", style=_TODO_STYLES.get(status, ""))
        return body

    def header_meta(self, items: list[dict]) -> str:
        done = sum(1 for t in items if t["status"] == "completed")
        return f"{done}/{len(items)}"

    def on_archive(self, app) -> None:
        # Reset for next turn — call TodoWrite again will log tool_use.
        self.tool_use_logged = False

    def reset(self) -> None:
        super().reset()
        self.tool_use_logged = False


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------

_BG_GLYPHS = {"running": "●", "completed": "✓", "error": "✕"}
_BG_STYLES = {
    "running": f"bold {GOLD}",
    "completed": f"dim {OK}",
    "error": "bold red",
}


class BackgroundPanel(LivePanel[tuple]):
    """Background-run tasks (workers spawned via the background_run tool).

    Items: ``(task_id, status, command)``. Polled at ~1Hz by the App so
    running → completed transitions show up live; ``skip_unchanged`` keeps
    the redraw cost negligible when nothing has moved.
    """

    def __init__(self) -> None:
        super().__init__(
            widget_id="bg",
            glyph="◆",
            accent=BRAND,
            title="background",
            done_accent=OK,
            skip_unchanged=True,
        )

    def snapshot(self) -> list[tuple]:
        tasks = state.BG.tasks
        return sorted(
            (tid, t.get("status", "?"), t.get("command", ""))
            for tid, t in tasks.items()
        )

    def signature(self, items: list[tuple]) -> tuple:
        return tuple((tid, status) for tid, status, _ in items)

    def all_settled(self, items: list[tuple]) -> bool:
        return not any(s == "running" for _, s, _ in items)

    def build_body(self, items: list[tuple]) -> Text:
        body = Text()
        for i, (tid, status, command) in enumerate(items):
            mark = _BG_GLYPHS.get(status, "?")
            cmd = command if len(command) <= 70 else command[:67] + "..."
            if i:
                body.append("\n")
            body.append(f"{mark}  {tid}  ", style=_BG_STYLES.get(status, ""))
            body.append(cmd, style="white")
        return body

    def header_meta(self, items: list[tuple]) -> str:
        running = sum(1 for _, s, _ in items if s == "running")
        return f"{running} running · {len(items)} total"
