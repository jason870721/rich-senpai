"""Textual REPL for chatting with the rich-senpai agent.

Layout:

  - Header at the top.
  - RichLog fills the middle, rendering assistant text, tool calls,
    tool results, and per-turn footers as Rich renderables.
  - Input at the bottom; Enter submits, up/down walks history.
  - Footer shows key bindings.

`AgentCore.run_turn` is synchronous and emits events through `on_event`
while it runs. We run each turn in a Textual worker (thread=True) and
funnel events back to the UI via `call_from_thread` so widget mutations
stay on the main thread.

Slash commands:
  /quit | /exit  -> leave (Ctrl+Q works too)
  /clear         -> reset the in-session message history (short_memory.md
                    is untouched; next turn re-frames from it)
  /help          -> list the slash commands
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from rich.console import Group
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.timer import Timer
from textual.widgets import Header, Input, RichLog, Static

import json

from core import AgentCore, CycleResult, state
from core.compaction import auto_compact
from core.llm import Message


HISTORY_PATH = Path.home() / ".rich_senpai_history"
TOOL_RESULT_PREVIEW_CHARS = 800
_QUIT_ALIASES = frozenset({"/quit", "/exit", "exit", "quit", "!q"})

# Braille spinner frames — 10 frames at 100ms = one revolution per second.
_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_SPINNER_INTERVAL = 0.1

# Palette — cyan is the primary brand for dialogue and chrome; gold marks
# active / in-progress / notable mid-turn events (skill load, wait,
# compact, drains, interrupt warnings); soft green marks completed
# states; grey50 carries all execution metadata. Red is reserved strictly
# for errors and exceptions.
_BRAND = "cyan"
_ACCENT = "bright_cyan"
_GOLD = "gold1"
_SUBTLE = "grey50"
_OK = "green3"

HELP_TEXT = """\
[bold]commands[/]
  [bold]/help[/]     show this help
  [bold]/clear[/]    reset the in-session message history (short_memory.md is untouched)
  [bold]/compact[/]  manually compress the in-session message history
  [bold]/tasks[/]    list every file-backed task
  [bold]/team[/]     list every spawned teammate
  [bold]/inbox[/]    drain the lead's inbox (visible to the user only)
  [bold]/quit[/]     exit (Ctrl+Q works too)

[bold]everything else[/] is sent to the agent as the next user turn."""


def _format_tool_input(tool_input: dict[str, Any]) -> str:
    if not tool_input:
        return ""
    parts: list[str] = []
    for k, v in tool_input.items():
        if isinstance(v, str) and len(v) > 80:
            v = v[:77] + "..."
        parts.append(f"{k}={v!r}")
    return ", ".join(parts)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [{len(text) - limit} more chars elided]"


def _block(marker: str, marker_style: str, header: Text, body: Any | None = None) -> Group:
    """Claude Code-style block: a marker glyph + header line, optional 2-space indented body."""
    head = Text()
    head.append(marker + "  ", style=marker_style)
    head.append_text(header)
    if body is None:
        return Group(head)
    return Group(head, Padding(body, (0, 0, 0, 3)))


def _bar_line(head: Text, *, glyph: str, bar_style: str = _BRAND) -> Text:
    """One-line tool-block row: `│ <glyph> <head>`. The `│` visually
    encapsulates the tool call so its result rows can hang underneath."""
    out = Text()
    out.append("│ ", style=bar_style)
    out.append(glyph + " ", style=bar_style)
    out.append_text(head)
    return out


def _bar_block_body(text: str, *, glyph: str = "⎿", bar_style: str = _BRAND, body_style: str = "dim") -> Text:
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


class HistoryInput(Input):
    """Input with up/down navigation over a persistent file history."""

    BINDINGS = [
        Binding("up", "history_prev", "prev", show=False),
        Binding("down", "history_next", "next", show=False),
    ]

    def __init__(
        self,
        *args: Any,
        history_path: Path | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._history_path = history_path
        self._history: list[str] = []
        self._idx: int | None = None
        if history_path and history_path.exists():
            try:
                self._history = [
                    line for line in history_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
            except OSError:
                pass

    def push_history(self, text: str) -> None:
        if not text:
            return
        if not self._history or self._history[-1] != text:
            self._history.append(text)
            if self._history_path is not None:
                try:
                    with self._history_path.open("a", encoding="utf-8") as f:
                        f.write(text + "\n")
                except OSError:
                    pass
        self._idx = None

    def action_history_prev(self) -> None:
        if not self._history:
            return
        self._idx = (
            len(self._history) - 1 if self._idx is None else max(0, self._idx - 1)
        )
        self.value = self._history[self._idx]
        self.cursor_position = len(self.value)

    def action_history_next(self) -> None:
        if self._idx is None:
            return
        self._idx += 1
        if self._idx >= len(self._history):
            self._idx = None
            self.value = ""
        else:
            self.value = self._history[self._idx]
            self.cursor_position = len(self.value)


class SenpaiApp(App):
    CSS = """
    Screen {
        background: $surface;
    }
    RichLog {
        height: 1fr;
        padding: 1 2;
        background: transparent;
        scrollbar-size: 0 0;
    }
    #status {
        height: 1;
        padding: 0 2;
    }
    #todos {
        height: auto;
        max-height: 14;
        padding: 0 2;
    }
    #bg {
        height: auto;
        max-height: 12;
        padding: 0 2;
    }
    HistoryInput {
        dock: bottom;
        border: none;
        border-top: solid #808080;
        background: $surface;
        padding: 0 1;
    }
    HistoryInput:focus {
        border-top: solid cyan;
    }
    HistoryInput:disabled {
        opacity: 0.6;
    }
    Header {
        background: $surface;
        color: cyan;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+l", "clear_history", "Clear"),
        # Esc cooperatively interrupts the current agent turn. Fires only
        # when busy; idle Esc is harmless.
        Binding("escape", "interrupt", "Interrupt", show=False),
    ]

    TITLE = "rich-senpai"
    SUB_TITLE = "interactive trading agent"

    def __init__(self) -> None:
        super().__init__()
        self.agent = AgentCore(on_event=self._on_agent_event)
        self.messages: list[Message] = []
        self.turn_no = 0
        self._busy = False
        self._model_label = self._describe_model()
        # thinking-indicator state
        self._spin_idx = 0
        self._busy_started_at: float | None = None
        self._status_label = ""
        self._status_iter = 0
        self._tick_timer: Timer | None = None
        # skills the model has loaded this session — used to surface a
        # banner when load_skill fires and an "active skills" footer.
        self._active_skills: set[str] = set()
        # tool_use ids whose tool_result we want to suppress in the log
        # (currently: load_skill, since its result is the entire skill body).
        self._suppressed_tool_ids: set[str] = set()
        # Snapshot of the last all-completed todo list we archived into the
        # log. Used to avoid re-archiving on subsequent refreshes that
        # see the same fully-done list.
        self._archived_todo_signature: tuple[tuple[str, str], ...] | None = None
        # Background-tasks panel: a 1Hz timer keeps it live while workers
        # are running so the user sees status transitions without waiting
        # for the next agent turn.
        self._bg_tick_timer: Timer | None = None
        self._last_bg_signature: tuple | None = None
        # Snapshot of the last all-settled background-tasks set we
        # archived into the log; mirrors _archived_todo_signature.
        self._archived_bg_signature: tuple | None = None

    def _describe_model(self) -> str:
        """Short string describing the active LLM, e.g. 'ollama · qwen3.6:latest'."""
        client = self.agent.llm
        provider = type(client).__name__.replace("LLMClient", "").lower() or "llm"
        model = getattr(client, "model", None) or "?"
        return f"{provider} ({model})"

    def _paint_welcome(self) -> None:
        """Render the full-width intro panel into the log. Two columns:
        greeting + capability list on the left, gold pyramid logo on the
        right. Called from on_mount and from /clear so a freshly reset
        screen still shows the brand + bindings."""
        greeting = Text()
        greeting.append("welcome back  ·  ", style=f"bold {_ACCENT}")
        greeting.append("ready when you are!\n\n", style=_ACCENT)
        greeting.append(
            "I am interactive trading agent - rich senpai \n\n"
            "skills, tools, todos, teammates, and a persistent\n"
            "short-memory scratchpad shared across sessions.\n\n",
            style="white",
        )
        for bullet in (
            "persistent short memory survives across turns",
            "background tasks & inbox-driven coordination",
        ):
            greeting.append("  ⌁  ", style=_GOLD)
            greeting.append(bullet + "\n", style="white")
        greeting.append("\n")
        greeting.append("model    · ", style="dim")
        greeting.append(self._model_label + "\n", style=_SUBTLE)
        greeting.append("session  · ", style="dim")
        greeting.append(
            datetime.now().strftime("%Y-%m-%d %H:%M"), style=_SUBTLE
        )
        greeting.append("\n\n")
        greeting.append(
            "/help  ·  /clear  ·  Esc to interrupt  ·  !q to exit",
            style="dim",
        )

        # Pre-padded so every row has the apex at column 6 of 13 — keeps
        # the pyramid centered no matter how its column is justified.
        # Gradient: bright at the apex, dimming toward the base.
        pyramid = Text()
        for i, (line, style) in enumerate([
            ("      ▲      ", f"bold {_GOLD}"),
            ("     ▲▲▲     ", f"bold {_GOLD}"),
            ("     ▲▲▲▲▲    ", _GOLD),
            ("     ▲▲▲▲▲▲▲   ", _GOLD),
            ("     ▲▲▲▲▲▲▲▲▲  ", "gold3"),
            ("     ▲▲▲▲▲▲▲▲▲▲▲ ", "gold3"),
        ]):
            if i:
                pyramid.append("\n")
            pyramid.append(line, style=style)

        grid = Table.grid(expand=True, padding=(0, 2))
        grid.add_column(ratio=3)
        grid.add_column(ratio=1, justify="center")
        grid.add_row(greeting, pyramid)

        self._write(
            Panel(
                grid,
                title=f"[bold {_BRAND}]✻ rich-senpai[/]",
                title_align="left",
                border_style=_BRAND,
                padding=(1, 2),
            )
        )
        self._write(Text(""))

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield RichLog(id="log", markup=True, highlight=False, wrap=True)
        # Todos panel sits above the status; auto-sized, hidden while empty.
        # Refreshed in place whenever the agent calls TodoWrite.
        yield Static("", id="todos")
        # Background tasks panel — sibling of todos, ticked once a second
        # so running → completed transitions show up live.
        yield Static("", id="bg")
        # Status sits in normal flow between the log and the docked input,
        # so it occupies a fixed 1-row band that's always visible.
        yield Static("", id="status")
        yield HistoryInput(
            placeholder="> type a message · /help · !q to exit",
            id="prompt",
            history_path=HISTORY_PATH,
        )

    def on_mount(self) -> None:
        self.sub_title = self._model_label
        self._paint_welcome()
        self._refresh_todos()
        self._refresh_bg()
        # 1Hz tick keeps the bg panel honest as worker threads finish
        # (state.BG.tasks mutates outside the agent thread).
        self._bg_tick_timer = self.set_interval(1.0, self._refresh_bg)
        self.query_one(HistoryInput).focus()

    def on_unmount(self) -> None:
        self.agent.close()

    # ----- rendering helpers -------------------------------------------------

    def _write(self, renderable: Any) -> None:
        self.query_one("#log", RichLog).write(renderable)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        prompt = self.query_one(HistoryInput)
        prompt.disabled = busy
        prompt.placeholder = (
            "agent is thinking…" if busy
            else "> type a message · /help · !q to exit"
        )
        status = self.query_one("#status", Static)
        if busy:
            self._busy_started_at = time.monotonic()
            self._spin_idx = 0
            self._status_label = "thinking"
            self._status_iter = 0
            self._tick_status()  # paint immediately so there's no blank gap
            self._tick_timer = self.set_interval(_SPINNER_INTERVAL, self._tick_status)
        else:
            if self._tick_timer is not None:
                self._tick_timer.stop()
                self._tick_timer = None
            self._busy_started_at = None
            status.update("")
        if not busy:
            prompt.focus()

    def _tick_status(self) -> None:
        if self._busy_started_at is None:
            return
        self._spin_idx = (self._spin_idx + 1) % len(_SPINNER_FRAMES)
        frame = _SPINNER_FRAMES[self._spin_idx]
        elapsed = time.monotonic() - self._busy_started_at
        line = Text.assemble(
            (f"{frame}  ", f"bold {_BRAND}"),
            (self._status_label, _BRAND),
            (f"   iter {self._status_iter}", "dim"),
            (f"   {elapsed:4.1f}s", "dim"),
            (f"   {self._model_label}", "dim"),
            ("   esc to interrupt", "dim"),
        )
        self.query_one("#status", Static).update(line)

    def _on_agent_event(self, event: dict[str, Any]) -> None:
        # Invoked from the worker thread inside agent.run_turn.
        self.call_from_thread(self._render_event, event)

    def _render_event(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        # Reflect the latest progress in the spinner line.
        self._status_iter = event.get("iteration", 0)
        self._status_label = self._status_label_for(event)
        renderer = self._EVENT_RENDERERS.get(kind)
        if renderer is not None:
            renderer(self, event)

    # ----- per-event renderers ---------------------------------------------

    def _render_assistant_text(self, event: dict[str, Any]) -> None:
        text = event["text"].strip()
        if not text:
            return
        header = Text()
        header.append("senpai", style=f"bold {_BRAND}")
        header.append(f"   iter {event.get('iteration', 0)}", style="dim")
        self._write(Text(""))  # breathing room above
        self._write(_block("⏺", _BRAND, header, Markdown(text)))

    def _render_tool_use(self, event: dict[str, Any]) -> None:
        name = event.get("name")
        # Special-cased tools have their own surface in the UI; suppress
        # both the tool_use line in the log and the matching tool_result.
        if name == "load_skill":
            self._render_skill_load(event)
            self._suppress(event.get("id"))
            return
        if name == "TodoWrite":
            # Bottom panel is the canonical view; don't echo to the log.
            self._suppress(event.get("id"))
            return
        args = _format_tool_input(event.get("input") or {})
        head = Text()
        head.append(name or "?", style=f"bold {_BRAND}")
        head.append("(", style="dim")
        head.append(args, style="dim")
        head.append(")", style="dim")
        head.append(f"   iter {event.get('iteration', 0)}", style="dim")
        self._write(Text(""))
        self._write(_bar_line(head, glyph="⏺", bar_style=_BRAND))

    def _render_tool_result(self, event: dict[str, Any]) -> None:
        tu_id = event.get("id")
        if tu_id and tu_id in self._suppressed_tool_ids:
            self._suppressed_tool_ids.discard(tu_id)
            if event.get("name") == "TodoWrite":
                self._refresh_todos()
            return
        output = _truncate(event["output"], TOOL_RESULT_PREVIEW_CHARS)
        self._write(_bar_block_body(output, glyph="⎿", bar_style=_BRAND, body_style="dim"))

    def _render_wait(self, event: dict[str, Any]) -> None:
        self._write(
            Text.assemble(
                ("⏸  ", _GOLD),
                ("wait", f"bold {_GOLD}"),
                (f"   iter {event.get('iteration', 0)} — sleeping {event.get('seconds', '?')}s", "dim"),
            )
        )

    def _render_compact(self, event: dict[str, Any]) -> None:
        self._write(
            Text.assemble(
                ("⌁  ", _GOLD),
                ("compact", f"bold {_GOLD}"),
                (f"   {event.get('reason', '')}", "dim"),
            )
        )

    def _render_background_drain(self, event: dict[str, Any]) -> None:
        n = len(event.get("notifications", []))
        self._write(
            Text.assemble(
                ("◇  ", _GOLD),
                ("background", f"bold {_GOLD}"),
                (f"   {n} notification(s) drained", "dim"),
            )
        )

    def _render_inbox_drain(self, event: dict[str, Any]) -> None:
        n = len(event.get("messages", []))
        self._write(
            Text.assemble(
                ("✉  ", _GOLD),
                ("inbox", f"bold {_GOLD}"),
                (f"   {n} message(s) drained", "dim"),
            )
        )

    def _render_interrupted(self, event: dict[str, Any]) -> None:
        stage = event.get("stage", "")
        suffix = f"   {stage}" if stage else ""
        self._write(
            Text.assemble(
                ("⏼  ", _GOLD),
                ("interrupted", f"bold {_GOLD}"),
                (f"   iter {event.get('iteration', 0)}{suffix}", "dim"),
            )
        )

    def _suppress(self, tu_id: str | None) -> None:
        if tu_id:
            self._suppressed_tool_ids.add(tu_id)

    # Map of agent-event ``type`` -> handler. Adding a new event kind:
    # write a `_render_<kind>` method and add the entry below.
    _EVENT_RENDERERS: dict[str, Callable[[SenpaiApp, dict[str, Any]], None]] = {
        "assistant_text": _render_assistant_text,
        "tool_use": _render_tool_use,
        "tool_result": _render_tool_result,
        "wait": _render_wait,
        "compact": _render_compact,
        "background_drain": _render_background_drain,
        "inbox_drain": _render_inbox_drain,
        "interrupted": _render_interrupted,
    }

    def _build_todos_panel(
        self,
        items: list[dict[str, str]],
        *,
        title: str = "todos",
        accent: str = _BRAND,
    ) -> Group:
        glyphs = {"completed": "✓", "in_progress": "▸", "pending": "○"}
        styles = {
            "completed": f"dim {_OK}",
            "in_progress": f"bold {_GOLD}",
            "pending": "white",
        }
        body = Text()
        for i, item in enumerate(items):
            status = item["status"]
            mark = glyphs.get(status, "?")
            label = item["activeForm"] if status == "in_progress" else item["content"]
            if i:
                body.append("\n")
            body.append(f"{mark}  {label}", style=styles.get(status, ""))
        done = sum(1 for t in items if t["status"] == "completed")
        header = Text()
        header.append(title, style=f"bold {accent}")
        header.append(f"   {done}/{len(items)}", style="dim")
        return _block("✦", accent, header, body)

    def _refresh_todos(self) -> None:
        """Repaint the docked todos panel from state.TODO.

        When every item is completed we archive the list into the
        scrolling log and hide the bottom panel — the next TodoWrite with
        new (incomplete) items will re-show it.
        """
        widget = self.query_one("#todos", Static)
        items = state.TODO.items

        if not items:
            widget.display = False
            widget.update("")
            return

        signature = tuple((t["content"], t["status"]) for t in items)
        all_done = all(t["status"] == "completed" for t in items)

        if all_done:
            if signature != self._archived_todo_signature:
                self._write(
                    self._build_todos_panel(
                        items, title="todos · all done", accent=_OK
                    )
                )
                self._archived_todo_signature = signature
            widget.display = False
            widget.update("")
            return

        # Mixed / in-progress list — clear any stale archive marker so the
        # next all-done snapshot re-archives cleanly.
        self._archived_todo_signature = None
        widget.display = True
        widget.update(self._build_todos_panel(items))

    def _build_bg_panel(
        self,
        snapshot: list[tuple[str, str, str]],
        *,
        title: str = "background",
        accent: str = _BRAND,
    ) -> Group:
        glyphs = {"running": "●", "completed": "✓", "error": "✕"}
        styles = {
            "running": f"bold {_GOLD}",
            "completed": f"dim {_OK}",
            "error": "bold red",
        }
        body = Text()
        for i, (tid, status, command) in enumerate(snapshot):
            mark = glyphs.get(status, "?")
            cmd = command if len(command) <= 70 else command[:67] + "..."
            if i:
                body.append("\n")
            body.append(f"{mark}  {tid}  ", style=styles.get(status, ""))
            body.append(cmd, style="white")
        running = sum(1 for _, s, _ in snapshot if s == "running")
        header = Text()
        header.append(title, style=f"bold {accent}")
        header.append(f"   {running} running · {len(snapshot)} total", style="dim")
        return _block("◆", accent, header, body)

    def _refresh_bg(self) -> None:
        """Repaint the docked background-tasks panel from state.BG.

        When every task has settled (no running) we archive the list into
        the scrolling log and hide the bottom panel — the next
        background_run that creates a running task will re-show it.
        """
        widget = self.query_one("#bg", Static)
        tasks = state.BG.tasks

        if not tasks:
            if self._last_bg_signature is not None:
                widget.display = False
                widget.update("")
                self._last_bg_signature = None
            return

        snapshot = sorted(
            (tid, t.get("status", "?"), t.get("command", ""))
            for tid, t in tasks.items()
        )
        signature = tuple((tid, status) for tid, status, _ in snapshot)
        if signature == self._last_bg_signature:
            return
        self._last_bg_signature = signature

        all_settled = not any(s == "running" for _, s, _ in snapshot)

        if all_settled:
            if signature != self._archived_bg_signature:
                self._write(
                    self._build_bg_panel(
                        snapshot,
                        title="background · all done",
                        accent=_OK,
                    )
                )
                self._archived_bg_signature = signature
            widget.display = False
            widget.update("")
            return

        # At least one task is still running — make sure the next
        # all-settled snapshot re-archives even if it matches a stale one.
        self._archived_bg_signature = None
        widget.display = True
        widget.update(self._build_bg_panel(snapshot))

    def _render_skill_load(self, event: dict[str, Any]) -> None:
        """Show a clear banner when the agent loads a skill, and remember
        which skills have been activated so the turn footer can list them."""
        name = (event.get("input") or {}).get("name") or "<unknown>"

        # Pull the skill description from the loader if it's a known skill;
        # show a hint when the model asks for one that doesn't exist.
        skill = state.SKILLS.skills.get(name)
        if skill:
            self._active_skills.add(name)
            description = str(skill.get("description", {})).strip() or "(no description)"
            available = True
        else:
            description = (
                "skill not found — agent will get an error result. "
                f"Available: {', '.join(sorted(state.SKILLS.skills.keys())) or '(none)'}"
            )
            available = False

        accent = _GOLD if available else "red"
        # Single-width glyphs only — wide emojis (📚, ❓) measure as
        # 2 cells in some fonts and 1 in others, which corrupts the
        # surrounding line layout. See module docstring.
        glyph = "✦" if available else "✕"
        label = "skill loaded" if available else "skill NOT FOUND"
        header = Text()
        header.append(label, style=f"bold {accent}")
        header.append("   ")
        header.append(name, style="bold")
        body = Text(description, style="dim")
        self._write(_block(glyph, accent, header, body))

    @staticmethod
    def _status_label_for(event: dict[str, Any]) -> str:
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

    def _write_turn_footer(self, result: CycleResult) -> None:
        usage = result.usage or {}
        skill_suffix = (
            f"   skills · {', '.join(sorted(self._active_skills))}"
            if self._active_skills
            else ""
        )
        self._write(
            Text.assemble(
                ("\n  ── ", "dim"),
                (f"#{self.turn_no}  ", f"bold {_BRAND}"),
                (f"stop={result.stop_reason}", "dim"),
                (f"   iters {result.iterations}", "dim"),
                (
                    f"   tok in {usage.get('input_tokens', 0)} · out {usage.get('output_tokens', 0)}",
                    "dim",
                ),
                (f"   {self._model_label}", "dim"),
                (skill_suffix, "dim"),
            )
        )

    # ----- input + worker ----------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return

        if self._busy:
            self._write(
                Text(
                    "[busy] please wait for the current turn to finish.",
                    style="bold red",
                )
            )
            return

        prompt = self.query_one(HistoryInput)
        prompt.push_history(text)

        # Slash commands and quit aliases are local — they never reach
        # the agent. Anything else is forwarded as the next user turn.
        if text in _QUIT_ALIASES:
            self.exit()
            return
        slash_handler = self._SLASH_COMMANDS.get(text)
        if slash_handler is not None:
            slash_handler(self)
            return

        self._write(Text(""))
        echo = Text()
        echo.append("▎ ", style=f"bold {_BRAND}")
        echo.append("> ", style=f"bold {_BRAND}")
        echo.append(text, style="bold white")
        self._write(echo)
        self._write(Text(""))
        self.turn_no += 1
        self._set_busy(True)
        self.run_worker(
            lambda t=text: self._run_turn_blocking(t),
            thread=True,
            exclusive=True,
            name="agent_turn",
        )

    # ----- slash-command handlers ------------------------------------------

    def _cmd_help(self) -> None:
        header = Text("commands", style=f"bold {_BRAND}")
        self._write(_block("✦", _BRAND, header, Text.from_markup(HELP_TEXT)))

    def _cmd_clear(self) -> None:
        self.action_clear_history()

    def _cmd_compact(self) -> None:
        self._compact_history()

    def _cmd_tasks(self) -> None:
        header = Text("tasks", style=f"bold {_ACCENT}")
        self._write(_block("✦", _ACCENT, header, Text(state.TASK_MGR.list_all())))

    def _cmd_team(self) -> None:
        header = Text("team", style=f"bold {_ACCENT}")
        self._write(_block("✦", _ACCENT, header, Text(state.get_team().list_all())))

    def _cmd_inbox(self) -> None:
        inbox = state.BUS.read_inbox(state.LEAD_NAME)
        body = json.dumps(inbox, indent=2) if inbox else "(empty)"
        header = Text("inbox", style=f"bold {_ACCENT}")
        self._write(_block("✦", _ACCENT, header, Text(body)))

    _SLASH_COMMANDS: dict[str, Callable[[SenpaiApp], None]] = {
        "/help": _cmd_help,
        "/clear": _cmd_clear,
        "/compact": _cmd_compact,
        "/tasks": _cmd_tasks,
        "/team": _cmd_team,
        "/inbox": _cmd_inbox,
    }

    def _run_turn_blocking(self, user_input: str) -> None:
        try:
            result = self.agent.run_turn(self.messages, user_input)
        except Exception as exc:
            self.call_from_thread(self._on_turn_error, exc)
            return
        self.call_from_thread(self._on_turn_done, result)

    def _on_turn_done(self, result: CycleResult) -> None:
        self._write_turn_footer(result)
        self._set_busy(False)

    def _on_turn_error(self, exc: Exception) -> None:
        self._write(Text(f"error: {exc!r}", style="bold red"))
        self._set_busy(False)

    def action_clear_history(self) -> None:
        if self._busy:
            return
        # Reset conversation state.
        self.messages.clear()
        self.turn_no = 0
        # Per-session UI bookkeeping that should not bleed across a reset.
        self._suppressed_tool_ids.clear()
        self._active_skills.clear()
        self._archived_todo_signature = None
        self._archived_bg_signature = None
        self._last_bg_signature = None
        # Wipe the scrolling log, then re-paint the intro so the screen
        # isn't blank. Refresh the docked panels in case TODO/BG state is
        # still live from a prior turn.
        self.query_one("#log", RichLog).clear()
        self._paint_welcome()
        self._write(
            Text(
                "history cleared. next turn will re-read short_memory.md",
                style="dim",
            )
        )
        self._refresh_todos()
        self._refresh_bg()

    def action_interrupt(self) -> None:
        """Esc — cooperatively cancel the in-flight agent turn. The agent
        checks the flag at iteration boundaries, so the current LLM call
        finishes before we return; further iterations / tool dispatch are
        skipped. No-op when idle."""
        if not self._busy or self._status_label == "interrupting…":
            return
        self.agent.request_interrupt()
        self._status_label = "interrupting…"
        self._write(
            Text(
                "⏼  interrupt requested — stopping after the current step",
                style=f"bold {_GOLD}",
            )
        )

    def _compact_history(self) -> None:
        if self._busy:
            self._write(Text("[busy] cannot compact mid-turn", style="bold red"))
            return
        if not self.messages:
            self._write(Text("nothing to compact yet.", style="dim"))
            return
        self._write(Text("compacting history…", style="dim"))
        # Drive the spinner so the user sees motion; the actual LLM call has
        # to run off the asyncio loop or it will block the UI for seconds and
        # Textual's watchdog will tear the app down.
        self._set_busy(True)
        self._status_label = "compacting context…"
        self.run_worker(
            self._compact_blocking,
            thread=True,
            exclusive=True,
            name="compact_history",
        )

    def _compact_blocking(self) -> None:
        try:
            new_msgs = auto_compact(
                self.messages,
                llm=self.agent.llm,
                system=self.agent.system_prompt,
            )
        except Exception as exc:  # noqa: BLE001 — we want every error visible
            self.call_from_thread(self._on_compact_error, exc)
            return
        self.call_from_thread(self._on_compact_done, new_msgs)

    def _on_compact_done(self, new_msgs) -> None:
        self.messages[:] = new_msgs
        self._set_busy(False)
        self._write(Text("history compacted.", style="dim"))

    def _on_compact_error(self, exc: Exception) -> None:
        self._set_busy(False)
        self._write(Text(f"compact failed: {exc!r}", style="bold red"))


def main() -> None:
    SenpaiApp().run()
