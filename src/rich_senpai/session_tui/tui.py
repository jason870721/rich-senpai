"""Textual REPL for chatting with the rich-senpai agent.

Layout (top → bottom):

  Header
  RichLog            — scrolling log, fills remaining space
  todos / bg / coworkers — docked LivePanels, hide when idle
  status             — busy spinner row
  #input_dock        — pinned-bottom Vertical:
    input_hint       — placeholder shown only when buffer is empty and the
                       agent is idle; cleared while typing or looping
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

from rich.markdown import Markdown
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.timer import Timer
from textual.widgets import Header, RichLog, Static

from rich_senpai import __version__
from rich_senpai.core import AgentCore, CycleResult, state
from rich_senpai.core.unit.agent import auto_compact
from rich_senpai.core.llm import Message
from rich_senpai.session_tui import commands, tips
from rich_senpai.session_tui.events import render_event, status_label_for
from rich_senpai.session_tui.panels import BackgroundPanel, CoworkerPanel, TodosPanel
from rich_senpai.session_tui.render import (
    block,
    format_input_stats,
    format_status_line,
    format_turn_footer,
    format_user_echo,
)
from rich_senpai.session_tui.style import (
    BRAND,
    GOLD,
    HISTORY_PATH,
    QUIT_ALIASES,
    SPINNER_FRAMES,
    SPINNER_INTERVAL,
)
from rich_senpai.session_tui.welcome import paint_welcome
from rich_senpai.session_tui.widgets import HistoryInput


_CONTINUE_HINT = "Enter ↵ continue · Esc to stop · or type to redirect"


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
        # Rotating-tips state for the `#input_hint` placeholder row. The
        # timer advances ``_tip_idx`` every ``tips.ROTATION_SECONDS`` and
        # repaints the hint only when both user and agent are idle. A
        # second timer (``_tip_anim_timer``) drives a per-character
        # typewriter reveal of the active tip and is cancelled the moment
        # the user types or the agent goes busy.
        self._tip_idx: int = 0
        self._tip_timer: Timer | None = None
        self._tip_anim_timer: Timer | None = None
        self._tip_anim_text: str = ""
        self._tip_anim_pos: int = 0
        # Typewriter reveal for the agent's text reply. While streaming,
        # the partial body lives in the `#streaming` Static (plain Text);
        # when the reveal completes (or is interrupted by a new event /
        # new turn) the full Markdown-rendered block is committed to the
        # log. Other event kinds (tool_use, tool_result, …) bypass this
        # path and render to the log directly as before. If the turn
        # finishes while the reveal is still in flight, the footer is
        # parked on ``_pending_turn_footer`` and drained by
        # ``_finalize_stream`` so it always lands beneath the reply.
        self._stream_full_text: str = ""
        self._stream_pos: int = 0
        self._stream_iter: int = 0
        self._stream_timer: Timer | None = None
        self._pending_turn_footer: CycleResult | None = None
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
        # When the agent returns ``stop_reason="max_iterations"`` the UI
        # parks in a tri-state continuation prompt: empty Enter resumes the
        # loop (``continue_run``), text Enter starts a fresh turn with that
        # text, and Esc abandons the continuation. Set only between turns,
        # so the input is unlocked (``_busy`` is False) while the flag is
        # True — distinct from the in-flight interrupt path.
        self._awaiting_continue: bool = False

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
        """Show the current rotating tip only when the buffer is empty.

        The hint row behaves like a placeholder — it surfaces a tip while
        the input is empty and the agent is idle, and disappears the
        moment the user starts typing. Busy-state hiding is owned by
        ``_set_busy``; the tip rotation itself is driven by
        ``_rotate_tip`` on a ``tips.ROTATION_SECONDS`` interval.

        When ``_awaiting_continue`` is set, the hint is hijacked to show
        the continuation prompt regardless of buffer content, so the user
        always sees how to resume / stop / redirect."""
        hint = self.query_one("#input_hint", Static)
        if self._awaiting_continue:
            hint.update(_CONTINUE_HINT)
            return
        prompt = self.query_one(HistoryInput)
        hint.update(tips.tip_at(self._tip_idx) if not prompt.text else "")

    def _rotate_tip(self) -> None:
        """Advance to the next tip and start the typewriter reveal if the
        hint is currently visible. The timer fires regardless of state —
        the visibility gate (buffer empty AND agent idle) is re-checked
        here so we don't clobber the typing/busy view, and the index
        still advances so the next idle window doesn't park on the same
        tip forever."""
        self._tip_idx += 1
        if self._busy or self._awaiting_continue:
            return
        prompt = self.query_one(HistoryInput)
        if prompt.text:
            return
        self._start_tip_animation(tips.tip_at(self._tip_idx))

    def _start_tip_animation(self, tip: str) -> None:
        """Begin the per-character reveal of ``tip`` in `#input_hint`.

        Any in-flight animation is cancelled first so the new tip starts
        from char 0. The first character paints immediately so there's
        no perceptible blank gap at the start of the reveal."""
        self._cancel_tip_animation()
        self._tip_anim_text = tip
        self._tip_anim_pos = 0
        self._tip_anim_timer = self.set_interval(
            tips.TYPING_INTERVAL_SECONDS, self._tip_anim_tick
        )
        self._tip_anim_tick()

    def _cancel_tip_animation(self) -> None:
        if self._tip_anim_timer is not None:
            self._tip_anim_timer.stop()
            self._tip_anim_timer = None

    def _tip_anim_tick(self) -> None:
        """Reveal one more character of the active tip. Re-checks the
        idle gate every tick so the animation aborts cleanly if the user
        starts typing or the agent enters a turn mid-reveal."""
        if self._busy or self._awaiting_continue:
            self._cancel_tip_animation()
            return
        prompt = self.query_one(HistoryInput)
        if prompt.text:
            self._cancel_tip_animation()
            return
        self._tip_anim_pos += 1
        self.query_one("#input_hint", Static).update(
            self._tip_anim_text[: self._tip_anim_pos]
        )
        if self._tip_anim_pos >= len(self._tip_anim_text):
            self._cancel_tip_animation()

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
        # Streaming buffer for the agent's in-progress text reply. Empty
        # (height collapses to 0) while idle; hosts the per-character
        # typewriter reveal during `assistant_text` events. The fully
        # Markdown-rendered block is committed to `#log` once the reveal
        # completes (or is interrupted).
        yield Static("", id="streaming")
        # Status sits in normal flow between the log and the docked input,
        # so it occupies a fixed 1-row band that's always visible.
        yield Static("", id="status")
        # Input dock — single Vertical that pins to the bottom. Children
        # flow top-to-bottom: keymap/placeholder hint → chevron + input
        # row → session stats line.
        with Vertical(id="input_dock"):
            yield Static(tips.tip_at(0), id="input_hint")
            with Horizontal(id="prompt_row"):
                yield Static("❯", id="prompt_chevron")
                yield HistoryInput(
                    id="prompt",
                    history_path=HISTORY_PATH,
                )
            yield Static("", id="input_stats")

    def on_mount(self) -> None:
        self.sub_title = f"v{__version__}  ·  {self._model_label}"
        paint_welcome(self.write, self._model_label)
        self.todos_panel.refresh(self)
        self.bg_panel.refresh(self)
        self.coworker_panel.refresh(self)
        self._refresh_input_stats()
        self._session_started_at = time.monotonic()
        self._bg_tick_timer = self.set_interval(1.0, self._tick_panels)
        self._tip_timer = self.set_interval(tips.ROTATION_SECONDS, self._rotate_tip)
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
        """Show the placeholder only while the buffer is empty; clear the
        hint row the moment the user types anything. Textual auto-routes
        ``TextArea.Changed`` to ``on_text_area_changed`` — naming this
        after the subclass would skip dispatch since
        ``HistoryInput.Changed`` is just an alias. Skipped while the
        agent is busy — ``_set_busy`` owns the hint then."""
        if self._busy:
            return
        if event.text_area.text:
            # User started typing — abort any in-flight typewriter reveal
            # and clear the hint row so it doesn't compete with their text.
            self._cancel_tip_animation()
            self.query_one("#input_hint", Static).update("")
        else:
            self.query_one("#input_hint", Static).update(tips.tip_at(self._tip_idx))

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
            # While the agent is looping the status spinner row owns the
            # "what's happening" channel — clear the hint so it doesn't
            # double up with stale guidance, and stop any tip-typewriter
            # reveal that may be mid-flight. A new turn also means any
            # in-flight assistant-text stream from the previous turn
            # should be promoted to the log right now (we don't want a
            # partial reveal hanging while the new round renders).
            self._cancel_tip_animation()
            self._finalize_stream()
            hint.update("")
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
        # Any non-assistant event mid-stream means the assistant chunk is
        # logically done — commit it to the log before rendering the new
        # event so timeline order is preserved (tool_use shouldn't appear
        # in the log "above" a still-streaming reply).
        if event.get("type") != "assistant_text" and self._stream_timer is not None:
            self._finalize_stream()
        render_event(self, event)

    # ----- assistant-text typewriter ---------------------------------------

    def start_streaming(self, text: str, iteration: int) -> None:
        """Begin a per-character reveal of the agent's text reply in
        `#streaming`. Any in-flight reveal is finalized first so its
        Markdown form lands in the log before the new one starts."""
        self._finalize_stream()
        self._stream_full_text = text
        self._stream_pos = 0
        self._stream_iter = iteration
        self._stream_timer = self.set_interval(STREAM_INTERVAL, self._stream_tick)
        self._stream_tick()  # paint the first chunk immediately

    def _stream_tick(self) -> None:
        self._stream_pos = min(
            self._stream_pos + STREAM_CHARS_PER_TICK,
            len(self._stream_full_text),
        )
        self._paint_stream_partial()
        if self._stream_pos >= len(self._stream_full_text):
            self._finalize_stream()

    def _paint_stream_partial(self) -> None:
        header = Text()
        header.append("senpai", style=f"bold {BRAND}")
        header.append(f"   iter {self._stream_iter}", style="dim")
        self.query_one("#streaming", Static).update(
            block(
                "⏺",
                BRAND,
                header,
                Text(self._stream_full_text[: self._stream_pos]),
            )
        )

    def _finalize_stream(self) -> None:
        """Stop the reveal timer (if any), commit the full reply to the
        log as a Markdown block, and clear the streaming widget. Drains
        a deferred turn footer last so the footer always lands beneath
        the reply it belongs to. Safe to call when no stream is active —
        the timer-stop and reply-commit become no-ops, but a deferred
        footer (parked because the turn ended mid-reveal) is still
        flushed so it can't get orphaned."""
        if self._stream_timer is not None:
            self._stream_timer.stop()
            self._stream_timer = None
        if self._stream_full_text:
            header = Text()
            header.append("senpai", style=f"bold {BRAND}")
            header.append(f"   iter {self._stream_iter}", style="dim")
            self.write(Text(""))  # breathing room above
            self.write(block("⏺", BRAND, header, Markdown(self._stream_full_text)))
            self.query_one("#streaming", Static).update("")
            self._stream_full_text = ""
            self._stream_pos = 0
        if self._pending_turn_footer is not None:
            footer = self._pending_turn_footer
            self._pending_turn_footer = None
            self._write_turn_footer(footer)

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

        # max_iterations continuation prompt — empty Enter resumes the
        # loop, non-empty falls through to the normal new-turn path
        # (which will overwrite the continuation with a fresh turn).
        if self._awaiting_continue and not self._busy:
            if not text:
                self._awaiting_continue = False
                self._set_input_hint_for_buffer()
                self._start_continue_turn()
                return
            # Non-empty: drop the continuation, let the new turn take over.
            self._awaiting_continue = False
            self._set_input_hint_for_buffer()

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

    def _start_continue_turn(self) -> None:
        """Resume the agent loop after a max_iterations pause.

        Counterpart to ``_run_turn_async`` for the empty-Enter branch of
        the continuation prompt — no user echo, no turn_no bump (this is
        the same logical turn continuing), and the agent's ``continue_run``
        runs the loop on the existing message list with the iteration
        counter reset to 0.
        """
        self._set_busy(True)
        self.run_worker(
            self._continue_turn_async(),
            exclusive=True,
            name="agent_turn",
        )

    async def _continue_turn_async(self) -> None:
        try:
            result = await self.agent.continue_run(self.messages)
        except Exception as exc:  # noqa: BLE001 — surface every error to the user
            self._on_turn_error(exc)
            return
        self._on_turn_done(result)

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
        if self._stream_timer is not None:
            # Reveal is still typing out the reply — park the footer so
            # it can be drained right after the assistant block lands in
            # the log, instead of slipping above the still-streaming
            # widget.
            self._pending_turn_footer = result
        else:
            self._write_turn_footer(result)
        self._set_busy(False)
        # If the agent stopped at the iteration budget, park in the
        # continuation prompt. ``_set_busy(False)`` already restored the
        # hint to the rotating tip; flip the flag and repaint so the
        # placeholder shows the continue/stop/redirect copy instead.
        if result.stop_reason == "max_iterations":
            self._awaiting_continue = True
            self._cancel_tip_animation()
            self._set_input_hint_for_buffer()
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
        # If we were parked at a max_iterations prompt, drop it — the
        # conversation it was tied to no longer exists.
        self._awaiting_continue = False
        # Recovery map keys (tool_use_ids) are tied to the message list
        # we just wiped — clear so /clear doesn't leak old originals
        # into the next conversation.
        self.agent._recovery_map.clear()
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
        skipped. While idle in a max_iterations continuation prompt, Esc
        instead abandons the continuation. No-op when fully idle."""
        if self._awaiting_continue and not self._busy:
            self._awaiting_continue = False
            self._set_input_hint_for_buffer()
            self.write(
                Text(
                    "↩  stopped at max iterations — type a new instruction to continue.",
                    style="dim",
                )
            )
            return
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

# Placeholder hint shown in the row above the input. Visible only while
# both the user and the agent are idle — i.e. the buffer is empty and the
# ReAct loop is not running. When the user starts typing the hint is
# cleared (so it doesn't compete with their own text); when the agent
# starts looping the status spinner row takes over. The body of the hint
# is a rotating tip drawn from ``session_tui.tips.TIPS``.

# Typewriter reveal cadence for the agent's text reply. Two chars per
# 15 ms tick ≈ 133 chars/sec — roughly 3× the tips reveal speed
# (one char per 25 ms = 40 chars/sec). Tune in tandem if either feels off.
STREAM_INTERVAL: float = 0.015
STREAM_CHARS_PER_TICK: int = 2


def main() -> None:
    SenpaiApp().run()
