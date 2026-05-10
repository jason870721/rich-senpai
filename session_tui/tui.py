"""Textual REPL for chatting with the rich-senpai agent.

Layout (top → bottom):

  Header
  RichLog            — scrolling log, fills remaining space
  todos / bg / coworkers — docked LivePanels, hide when idle
  status             — busy spinner row
  #input_dock        — pinned-bottom Vertical:
    input_hint       — placeholder / keymap / "agent is thinking…"
    prompt_row       — chevron + multi-line HistoryInput
    input_stats      — model · tokens · iter · uptime

CSS lives in ``styles.tcss`` next to this module. Pure rendering helpers
live in ``render.py``. Slash-command handlers live in ``commands.py``.
This file is the App orchestrator — it wires inputs, the agent worker,
panel ticks, and the busy spinner.

`AgentCore.run_turn` is async and emits events through ``on_event``
while it runs. We schedule each turn as an asyncio worker on the same
loop Textual is using; ``on_event`` callbacks run on that loop too,
so widget mutations don't need a thread hop.

Input UX:

  Enter        submit
  Shift+Enter  newline (multi-line input)
  Ctrl+Up/Dn   walk persisted command history
  Multi-line paste arrives via bracketed-paste; large pastes collapse
  to a `[paste #N: NNN chars, M lines]` marker that re-expands on submit.
  Hold Shift while click-dragging in the log to bypass mouse capture
  and use the terminal's native text selection (then copy with the
  terminal's usual binding — Cmd-C / Ctrl-Shift-C).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.timer import Timer
from textual.widgets import Header, RichLog, Static

from core import AgentCore, CycleResult, state
from core.compaction import auto_compact
from core.llm import Message
from session_tui import commands
from session_tui.events import render_event, status_label_for
from session_tui.panels import BackgroundPanel, CoworkerPanel, TodosPanel
from session_tui.render import (
    format_input_stats,
    format_status_line,
    format_turn_footer,
    format_user_echo,
)
from session_tui.style import (
    BRAND,
    GOLD,
    HISTORY_PATH,
    QUIT_ALIASES,
    SPINNER_FRAMES,
    SPINNER_INTERVAL,
)
from session_tui.welcome import paint_welcome
from session_tui.widgets import HistoryInput


class SenpaiApp(App):
    CSS_PATH = str(Path(__file__).parent / "styles.tcss")

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
        self.coworker_panel = CoworkerPanel()
        # 1Hz tick keeps the bg + coworker panels honest as worker threads
        # and teammate asyncio tasks mutate state outside the agent thread.
        self._bg_tick_timer: Timer | None = None
        # Cached so /copy can write the most recent agent reply to the
        # system clipboard without re-walking the message list.
        self._last_assistant_text: str = ""
        # Session-wide counters surfaced in the stats row beneath the
        # input. Tokens are summed across every completed turn; iters
        # tallies ReAct iterations across the session. Uptime is derived
        # from `_session_started_at` on the 1Hz panel tick.
        self._session_started_at: float = time.monotonic()
        self._total_in_tokens: int = 0
        self._total_out_tokens: int = 0
        self._total_iters: int = 0

    @property
    def last_assistant_text(self) -> str:
        """Most recent agent reply — read by ``commands.cmd_copy``."""
        return self._last_assistant_text

    def _describe_model(self) -> str:
        """Short string describing the active LLM, e.g. 'ollama (qwen3.6:latest)'."""
        client = self.agent.llm
        provider = type(client).__name__.replace("LLMClient", "").lower() or "llm"
        model = getattr(client, "model", None) or "?"
        return f"{provider} ({model})"

    def _set_input_hint_for_buffer(self) -> None:
        """Restore the hint based on whether the input buffer is empty."""
        prompt = self.query_one(HistoryInput)
        text = _PLACEHOLDER_HINT if not prompt.text else _KEYMAP_HINT
        self.query_one("#input_hint", Static).update(text)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield RichLog(id="log", markup=True, highlight=False, wrap=True)
        # Todos panel sits above the status; auto-sized, hidden while empty.
        yield Static("", id="todos")
        # Background tasks panel — sibling of todos, ticked once a second
        # so running → completed transitions show up live.
        yield Static("", id="bg")
        # Coworkers panel — visible only while at least one teammate is
        # alive; hidden the moment the last one shuts down.
        yield Static("", id="coworkers")
        # Status sits in normal flow between the log and the docked input,
        # so it occupies a fixed 1-row band that's always visible.
        yield Static("", id="status")
        # Input dock — single Vertical that pins to the bottom. Children
        # flow top-to-bottom: keymap/placeholder hint → chevron + input
        # row → session stats line.
        with Vertical(id="input_dock"):
            yield Static(_PLACEHOLDER_HINT, id="input_hint")
            with Horizontal(id="prompt_row"):
                yield Static("❯", id="prompt_chevron")
                yield HistoryInput(
                    id="prompt",
                    history_path=HISTORY_PATH,
                )
            yield Static("", id="input_stats")

    def on_mount(self) -> None:
        self.sub_title = self._model_label
        paint_welcome(self.write, self._model_label)
        self.todos_panel.refresh(self)
        self.bg_panel.refresh(self)
        self.coworker_panel.refresh(self)
        self._refresh_input_stats()
        self._session_started_at = time.monotonic()
        self._bg_tick_timer = self.set_interval(1.0, self._tick_panels)
        self.query_one(HistoryInput).focus()

    def _tick_panels(self) -> None:
        """1Hz refresh for panels and the stats row. Panels are driven
        by external state mutations (background workers + teammate
        asyncio tasks); the stats row's uptime ticks every second.
        LivePanel's ``skip_unchanged`` keeps the panel calls cheap when
        nothing has moved."""
        self.bg_panel.refresh(self)
        self.coworker_panel.refresh(self)
        self._refresh_input_stats()

    def _refresh_input_stats(self) -> None:
        """Repaint the stats row beneath the input. Cheap enough to call
        on the 1Hz tick."""
        self.query_one("#input_stats", Static).update(
            format_input_stats(
                model_label=self._model_label,
                in_tokens=self._total_in_tokens,
                out_tokens=self._total_out_tokens,
                iters=self._total_iters,
                uptime_seconds=time.monotonic() - self._session_started_at,
            )
        )

    def on_text_area_changed(self, event: HistoryInput.Changed) -> None:
        """Toggle the hint between placeholder (empty buffer) and keymap
        (anything typed). Textual auto-routes ``TextArea.Changed`` to
        ``on_text_area_changed`` — naming this after the subclass would
        skip dispatch since ``HistoryInput.Changed`` is just an alias.
        Skipped while the agent is busy — ``_set_busy`` owns the hint
        at that point."""
        if self._busy:
            return
        self.query_one("#input_hint", Static).update(
            _KEYMAP_HINT if event.text_area.text else _PLACEHOLDER_HINT
        )

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
        hint = self.query_one("#input_hint", Static)
        if busy:
            self._busy_started_at = time.monotonic()
            self._spin_idx = 0
            self._status_label = "thinking"
            self._status_iter = 0
            self._tick_status()  # paint immediately so there's no blank gap
            self._tick_timer = self.set_interval(SPINNER_INTERVAL, self._tick_status)
        else:
            self._set_input_hint_for_buffer()
            if self._tick_timer is not None:
                self._tick_timer.stop()
                self._tick_timer = None
            self._busy_started_at = None
            self.query_one("#status", Static).update("")
            prompt.focus()

    def _tick_status(self) -> None:
        if self._busy_started_at is None:
            return
        self._spin_idx = (self._spin_idx + 1) % len(SPINNER_FRAMES)
        self.query_one("#status", Static).update(
            format_status_line(
                spinner_frame=SPINNER_FRAMES[self._spin_idx],
                label=self._status_label,
                iteration=self._status_iter,
                elapsed_seconds=time.monotonic() - self._busy_started_at,
                model_label=self._model_label,
            )
        )

    # ----- agent event plumbing --------------------------------------------

    def _on_agent_event(self, event: dict[str, Any]) -> None:
        # Agent runs on the same asyncio loop as the UI, so we can mutate
        # widgets directly — no thread hop needed.
        self._status_iter = event.get("iteration", 0)
        self._status_label = status_label_for(event)
        render_event(self, event)

    def _write_turn_footer(self, result: CycleResult) -> None:
        self.write(
            format_turn_footer(
                turn_no=self.turn_no,
                stop_reason=result.stop_reason,
                iterations=result.iterations,
                usage=result.usage,
                model_label=self._model_label,
                active_skills=self.active_skills,
            )
        )

    # ----- input + worker --------------------------------------------------

    def on_history_input_submitted(self, event: HistoryInput.Submitted) -> None:
        text = event.value.strip()
        event.widget.clear_buffer()
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
        if commands.dispatch(self, text):
            return

        self.write(Text(""))
        self.write(format_user_echo(text))
        self.write(Text(""))
        self.turn_no += 1
        self._set_busy(True)
        self.run_worker(
            self._run_turn_async(text),
            exclusive=True,
            name="agent_turn",
        )

    # ----- turn lifecycle --------------------------------------------------

    async def _run_turn_async(self, user_input: str) -> None:
        try:
            result = await self.agent.run_turn(self.messages, user_input)
        except Exception as exc:  # noqa: BLE001 — surface every error to the user
            self._on_turn_error(exc)
            return
        self._on_turn_done(result)

    def _on_turn_done(self, result: CycleResult) -> None:
        if result.final_text:
            self._last_assistant_text = result.final_text
        usage = result.usage or {}
        self._total_in_tokens += int(usage.get("input_tokens", 0))
        self._total_out_tokens += int(usage.get("output_tokens", 0))
        self._total_iters += int(result.iterations or 0)
        self._write_turn_footer(result)
        self._set_busy(False)
        self._refresh_input_stats()

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
        self.coworker_panel.reset()
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
        self.coworker_panel.refresh(self)

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

    def compact_history(self) -> None:
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


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# Hint shown above the input. Three modes the App rotates between:
#   _PLACEHOLDER_HINT  buffer empty, agent idle    — surfaces slash commands
#   _KEYMAP_HINT       buffer non-empty, agent idle — keymap reminder
#   _BUSY_HINT         agent in flight             — interrupt instructions
_PLACEHOLDER_HINT: str = commands.placeholder_summary()
_KEYMAP_HINT: str = (
    "↵ submit · !q exit"
)


def main() -> None:
    SenpaiApp().run()
