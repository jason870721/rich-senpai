"""Textual REPL for chatting with the rich-senpai agent.

Layout:

  - Header at the top.
  - RichLog fills the middle, rendering assistant text, tool calls,
    tool results, and per-turn footers as Rich renderables.
  - Live docked panels (todos, background) sit between log and input —
    each is a LivePanel subclass (see session_tui.panels).
  - Status row + input dock at the bottom.

`AgentCore.run_turn` is async and emits events through `on_event` while
it runs. We schedule each turn as an asyncio worker on the same loop
Textual is using; `on_event` callbacks run on that loop too, so widget
mutations don't need cross-thread hops.

Slash commands:
  /quit | /exit  -> leave (Ctrl+Q works too)
  /clear         -> reset the in-session message history (short_memory.md
                    is untouched; next turn re-frames from it)
  /help          -> list the slash commands
  /compact       -> manually compress the in-session history
  /tasks         -> list every file-backed task
  /team          -> list every spawned teammate
  /inbox         -> drain the lead's inbox (visible to user only)
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.timer import Timer
from textual.widgets import Header, Input, RichLog, Static

from core import AgentCore, CycleResult, state
from core.compaction import auto_compact
from core.llm import Message
from session_tui.events import render_event, status_label_for
from session_tui.panels import BackgroundPanel, TodosPanel
from session_tui.render import block
from session_tui.style import (
    ACCENT,
    BRAND,
    GOLD,
    HELP_TEXT,
    HISTORY_PATH,
    QUIT_ALIASES,
    SPINNER_FRAMES,
    SPINNER_INTERVAL,
)
from session_tui.welcome import paint_welcome
from session_tui.widgets import HistoryInput


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
        # Spinner state
        self._spin_idx = 0
        self._busy_started_at: float | None = None
        self._status_label = ""
        self._status_iter = 0
        self._tick_timer: Timer | None = None
        # Skills the model has loaded this session — used to surface a
        # banner when load_skill fires and an "active skills" footer.
        self.active_skills: set[str] = set()
        # tool_use ids whose tool_result we want to suppress in the log
        # (currently: load_skill, since its result is the entire skill
        # body; TodoWrite, since the docked panel is the canonical view).
        self._suppressed_tool_ids: set[str] = set()
        # Live panels — share the LivePanel scaffold, keep distinct visuals.
        self.todos_panel = TodosPanel()
        self.bg_panel = BackgroundPanel()
        # 1Hz tick keeps the bg panel honest as worker threads finish
        # (state.BG.tasks mutates outside the agent thread).
        self._bg_tick_timer: Timer | None = None

    def _describe_model(self) -> str:
        """Short string describing the active LLM, e.g. 'ollama (qwen3.6:latest)'."""
        client = self.agent.llm
        provider = type(client).__name__.replace("LLMClient", "").lower() or "llm"
        model = getattr(client, "model", None) or "?"
        return f"{provider} ({model})"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield RichLog(id="log", markup=True, highlight=False, wrap=True)
        # Todos panel sits above the status; auto-sized, hidden while empty.
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
        paint_welcome(self.write, self._model_label)
        self.todos_panel.refresh(self)
        self.bg_panel.refresh(self)
        self._bg_tick_timer = self.set_interval(1.0, lambda: self.bg_panel.refresh(self))
        self.query_one(HistoryInput).focus()

    def on_unmount(self) -> None:
        self.agent.close()

    # ----- log + busy helpers ----------------------------------------------

    def write(self, renderable: Any) -> None:
        """Append a renderable to the scrolling log. Public so per-event
        renderers (session_tui.events) and panels can call it."""
        self.query_one("#log", RichLog).write(renderable)

    def suppress_tool_id(self, tu_id: str | None) -> None:
        """Record a tool_use id whose tool_result should be hidden."""
        if tu_id:
            self._suppressed_tool_ids.add(tu_id)

    def consume_suppressed(self, tu_id: str | None) -> bool:
        """Return True iff the id was previously suppressed; clears it."""
        if tu_id and tu_id in self._suppressed_tool_ids:
            self._suppressed_tool_ids.discard(tu_id)
            return True
        return False

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
            self._tick_timer = self.set_interval(SPINNER_INTERVAL, self._tick_status)
        else:
            if self._tick_timer is not None:
                self._tick_timer.stop()
                self._tick_timer = None
            self._busy_started_at = None
            status.update("")
            prompt.focus()

    def _tick_status(self) -> None:
        if self._busy_started_at is None:
            return
        self._spin_idx = (self._spin_idx + 1) % len(SPINNER_FRAMES)
        frame = SPINNER_FRAMES[self._spin_idx]
        elapsed = time.monotonic() - self._busy_started_at
        line = Text.assemble(
            (f"{frame}  ", f"bold {BRAND}"),
            (self._status_label, BRAND),
            (f"   iter {self._status_iter}", "dim"),
            (f"   {elapsed:4.1f}s", "dim"),
            (f"   {self._model_label}", "dim"),
            ("   esc to interrupt", "dim"),
        )
        self.query_one("#status", Static).update(line)

    # ----- agent event plumbing --------------------------------------------

    def _on_agent_event(self, event: dict[str, Any]) -> None:
        # Agent runs on the same asyncio loop as the UI, so we can mutate
        # widgets directly — no thread hop needed.
        self._status_iter = event.get("iteration", 0)
        self._status_label = status_label_for(event)
        render_event(self, event)

    def _write_turn_footer(self, result: CycleResult) -> None:
        usage = result.usage or {}
        skill_suffix = (
            f"   skills · {', '.join(sorted(self.active_skills))}"
            if self.active_skills
            else ""
        )
        self.write(
            Text.assemble(
                ("\n  ── ", "dim"),
                (f"#{self.turn_no}  ", f"bold {BRAND}"),
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

    # ----- input + worker --------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return

        if self._busy:
            self.write(
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
        if text in QUIT_ALIASES:
            self.exit()
            return
        slash_handler = self._SLASH_COMMANDS.get(text)
        if slash_handler is not None:
            slash_handler(self)
            return

        self.write(Text(""))
        echo = Text()
        echo.append("▎ ", style=f"bold {BRAND}")
        echo.append("> ", style=f"bold {BRAND}")
        echo.append(text, style="bold white")
        self.write(echo)
        self.write(Text(""))
        self.turn_no += 1
        self._set_busy(True)
        self.run_worker(
            self._run_turn_async(text),
            exclusive=True,
            name="agent_turn",
        )

    # ----- slash-command handlers ------------------------------------------

    def _cmd_help(self) -> None:
        header = Text("commands", style=f"bold {BRAND}")
        self.write(block("✦", BRAND, header, Text.from_markup(HELP_TEXT)))

    def _cmd_clear(self) -> None:
        self.action_clear_history()

    def _cmd_compact(self) -> None:
        self._compact_history()

    def _cmd_tasks(self) -> None:
        header = Text("tasks", style=f"bold {ACCENT}")
        self.write(block("✦", ACCENT, header, Text(state.TASK_MGR.list_all())))

    def _cmd_team(self) -> None:
        header = Text("team", style=f"bold {ACCENT}")
        self.write(block("✦", ACCENT, header, Text(state.get_team().list_all())))

    def _cmd_inbox(self) -> None:
        inbox = state.BUS.read_inbox(state.LEAD_NAME)
        body = json.dumps(inbox, indent=2) if inbox else "(empty)"
        header = Text("inbox", style=f"bold {ACCENT}")
        self.write(block("✦", ACCENT, header, Text(body)))

    _SLASH_COMMANDS: dict[str, Callable[[SenpaiApp], None]] = {
        "/help": _cmd_help,
        "/clear": _cmd_clear,
        "/compact": _cmd_compact,
        "/tasks": _cmd_tasks,
        "/team": _cmd_team,
        "/inbox": _cmd_inbox,
    }

    # ----- turn lifecycle --------------------------------------------------

    async def _run_turn_async(self, user_input: str) -> None:
        try:
            result = await self.agent.run_turn(self.messages, user_input)
        except Exception as exc:  # noqa: BLE001 — surface every error to the user
            self._on_turn_error(exc)
            return
        self._on_turn_done(result)

    def _on_turn_done(self, result: CycleResult) -> None:
        self._write_turn_footer(result)
        self._set_busy(False)

    def _on_turn_error(self, exc: Exception) -> None:
        self.write(Text(f"error: {exc!r}", style="bold red"))
        self._set_busy(False)

    def action_clear_history(self) -> None:
        if self._busy:
            return
        # Reset conversation state.
        self.messages.clear()
        self.turn_no = 0
        # Per-session UI bookkeeping that should not bleed across a reset.
        self._suppressed_tool_ids.clear()
        self.active_skills.clear()
        # clear todos and background panels, and reset state
        state.reset() # clean TODOList and BG state.
        self.todos_panel.reset()
        self.bg_panel.reset()
        # Wipe the scrolling log, then re-paint the intro so the screen
        # isn't blank. Refresh the docked panels in case TODO/BG state is
        # still live from a prior turn.
        self.query_one("#log", RichLog).clear()
        paint_welcome(self.write, self._model_label)
        self.write(
            Text(
                "history cleared. next turn will re-read short_memory.md",
                style="dim",
            )
        )
        self.todos_panel.refresh(self)
        self.bg_panel.refresh(self)

    def action_interrupt(self) -> None:
        """Esc — cooperatively cancel the in-flight agent turn. The agent
        checks the flag at iteration boundaries, so the current LLM call
        finishes before we return; further iterations / tool dispatch are
        skipped. No-op when idle."""
        if not self._busy or self._status_label == "interrupting…":
            return
        self.agent.request_interrupt()
        self._status_label = "interrupting…"
        self.write(
            Text(
                "⏼  interrupt requested — try to interrupt current step",
                style=f"bold {GOLD}",
            )
        )

    # ----- /compact --------------------------------------------------------

    def _compact_history(self) -> None:
        if self._busy:
            self.write(Text("[busy] cannot compact mid-turn", style="bold red"))
            return
        if not self.messages:
            self.write(Text("nothing to compact yet.", style="dim"))
            return
        self.write(Text("compacting history…", style="dim"))
        # Drive the spinner so the user sees motion; the LLM call is awaited
        # on the same asyncio loop Textual runs on, so the UI stays responsive
        # while it's in flight.
        self._set_busy(True)
        self._status_label = "compacting context…"
        self.run_worker(
            self._compact_async(),
            exclusive=True,
            name="compact_history",
        )

    async def _compact_async(self) -> None:
        try:
            new_msgs = await auto_compact(
                self.messages,
                llm=self.agent.llm,
                system=self.agent.system_prompt,
            )
        except Exception as exc:  # noqa: BLE001 — we want every error visible
            self._on_compact_error(exc)
            return
        self._on_compact_done(new_msgs)

    def _on_compact_done(self, new_msgs: list[Message]) -> None:
        self.messages[:] = new_msgs
        self._set_busy(False)
        self.write(Text("history compacted.", style="dim"))

    def _on_compact_error(self, exc: Exception) -> None:
        self._set_busy(False)
        self.write(Text(f"compact failed: {exc!r}", style="bold red"))


def main() -> None:
    SenpaiApp().run()
