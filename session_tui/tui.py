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
from pathlib import Path
from typing import Any

from rich.console import Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.timer import Timer
from textual.widgets import Footer, Header, Input, RichLog, Static

import json

from core import AgentCore, CycleResult, state
from core.compaction import auto_compact
from core.llm import Message


HISTORY_PATH = Path.home() / ".rich_senpai_history"
TOOL_RESULT_PREVIEW_CHARS = 800

# Braille spinner frames — 10 frames at 100ms = one revolution per second.
_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_SPINNER_INTERVAL = 0.1

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
    RichLog {
        height: 1fr;
        border: round cyan;
        padding: 0 1;
    }
    #status {
        height: 1;
        padding: 0 1;
        color: cyan;
    }
    HistoryInput {
        dock: bottom;
        margin: 0 0 0 0;
    }
    HistoryInput:disabled {
        opacity: 0.6;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+l", "clear_history", "Clear"),
    ]

    TITLE = "rich-senpai"
    SUB_TITLE = "interactive trading agent"

    def __init__(self) -> None:
        super().__init__()
        self.agent = AgentCore(on_event=self._on_agent_event)
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

    def _describe_model(self) -> str:
        """Short string describing the active LLM, e.g. 'ollama · qwen3.6:latest'."""
        client = self.agent.llm
        provider = type(client).__name__.replace("LLMClient", "").lower() or "llm"
        model = getattr(client, "model", None) or "?"
        return f"{provider} · {model}"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield RichLog(id="log", markup=True, highlight=False, wrap=True)
        # Status sits in normal flow between the log and the docked input,
        # so it occupies a fixed 1-row band that's always visible.
        yield Static("", id="status")
        yield HistoryInput(
            placeholder=">>> type a message · /help for commands",
            id="prompt",
            history_path=HISTORY_PATH,
        )
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = self._model_label
        self._write(
            Panel(
                Group(
                    Text("rich-senpai · interactive trading agent", style="bold cyan"),
                    Text(f"model: {self._model_label}", style="cyan"),
                    Text("type /help for commands · Ctrl+Q to exit", style="dim"),
                ),
                border_style="cyan",
            )
        )
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
            else ">>> type a message · /help for commands"
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
            (f" {frame}  ", "bold cyan"),
            (self._status_label, "cyan"),
            (f"  · iter {self._status_iter}", "dim"),
            (f"  · {elapsed:4.1f}s", "dim"),
            (f"  · {self._model_label}", "dim"),
        )
        self.query_one("#status", Static).update(line)

    def _on_agent_event(self, event: dict[str, Any]) -> None:
        # Invoked from the worker thread inside agent.run_turn.
        self.call_from_thread(self._render_event, event)

    def _render_event(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        i = event.get("iteration", 0)
        # Reflect the latest progress in the spinner line.
        self._status_iter = i
        self._status_label = self._status_label_for(event)
        if kind == "assistant_text":
            text = event["text"].strip()
            if not text:
                return
            self._write(
                Panel(
                    Markdown(text),
                    title=f"[bold cyan]assistant[/]  [dim]iter {i}[/]",
                    title_align="left",
                    border_style="cyan",
                )
            )
        elif kind == "tool_use":
            args = _format_tool_input(event["input"])
            self._write(
                Text.assemble(
                    ("→ ", "yellow"),
                    ("tool_use ", "bold yellow"),
                    (f"iter {i}  ", "dim"),
                    (event["name"], "bold"),
                    ("(", "dim"),
                    (args, ""),
                    (")", "dim"),
                )
            )
        elif kind == "tool_result":
            output = _truncate(event["output"], TOOL_RESULT_PREVIEW_CHARS)
            self._write(
                Panel(
                    Text(output, style="dim"),
                    title=f"[yellow]tool_result[/]  [dim]iter {i}[/]",
                    title_align="left",
                    border_style="yellow",
                )
            )
        elif kind == "wait":
            self._write(
                Text.assemble(
                    ("✓ ", "green"),
                    ("wait", "bold green"),
                    (f"  iter {i} — cycle complete", "dim"),
                )
            )
        elif kind == "compact":
            self._write(
                Text.assemble(
                    ("⌁ ", "magenta"),
                    ("compact", "bold magenta"),
                    (f"  {event.get('reason', '')}", "dim"),
                )
            )
        elif kind == "background_drain":
            n = len(event.get("notifications", []))
            self._write(
                Text.assemble(
                    ("◇ ", "cyan"),
                    ("background", "bold cyan"),
                    (f"  {n} notification(s) drained", "dim"),
                )
            )
        elif kind == "inbox_drain":
            n = len(event.get("messages", []))
            self._write(
                Text.assemble(
                    ("✉ ", "cyan"),
                    ("inbox", "bold cyan"),
                    (f"  {n} message(s) drained", "dim"),
                )
            )

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
            return "wrapping up"
        return "thinking"

    def _write_turn_footer(self, result: CycleResult) -> None:
        usage = result.usage or {}
        self._write(
            Text.assemble(
                (f"\n#{self.turn_no}  ", "dim"),
                (f"stop={result.stop_reason}  ", "bold"),
                (f"iters={result.iterations}  ", ""),
                (
                    f"tok in={usage.get('input_tokens', 0)} "
                    f"out={usage.get('output_tokens', 0)}  ",
                    "dim",
                ),
                (f"[{self._model_label}]", "cyan"),
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

        if text in {"/quit", "/exit"}:
            self.exit()
            return
        if text == "/help":
            self._write(Panel(HELP_TEXT, border_style="dim"))
            return
        if text == "/clear":
            self.action_clear_history()
            return
        if text == "/compact":
            self._compact_history()
            return
        if text == "/tasks":
            self._write(Panel(state.TASK_MGR.list_all(), border_style="dim"))
            return
        if text == "/team":
            self._write(Panel(state.get_team().list_all(), border_style="dim"))
            return
        if text == "/inbox":
            inbox = state.BUS.read_inbox(state.LEAD_NAME)
            self._write(Panel(json.dumps(inbox, indent=2) or "(empty)", border_style="dim"))
            return

        self._write(Text.assemble(("> ", "bold magenta"), (text, "")))
        self.turn_no += 1
        self._set_busy(True)
        self.run_worker(
            lambda t=text: self._run_turn_blocking(t),
            thread=True,
            exclusive=True,
            name="agent_turn",
        )

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
        self.messages.clear()
        self.turn_no = 0
        self._write(
            Text(
                "history cleared. next turn will re-read short_memory.md",
                style="dim",
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
