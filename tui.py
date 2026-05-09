"""Rich REPL for chatting with the rich-senpai agent.

Runs an interactive loop:

  - prompt_toolkit handles input (with persistent file history).
  - rich renders assistant text, tool calls, tool results, and usage stats.
  - Each user message becomes one AgentCore.run_turn call against a
    messages list that persists for the lifetime of the session, so the
    model sees the full conversation, not just the latest turn.

Slash commands:
  /quit | /exit  → leave (Ctrl+D works too)
  /clear         → reset the in-session message history (short_memory.md
                   is untouched; next turn re-frames from it)
  /help          → list the slash commands
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from core import AgentCore


HISTORY_PATH = Path.home() / ".rich_senpai_history"
TOOL_RESULT_PREVIEW_CHARS = 800


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


def make_event_renderer(console: Console):
    def render(event: dict[str, Any]) -> None:
        kind = event.get("type")
        i = event.get("iteration", 0)
        if kind == "assistant_text":
            text = event["text"].strip()
            if not text:
                return
            console.print(
                Panel(
                    Markdown(text),
                    title=f"[bold cyan]assistant[/]  [dim]iter {i}[/]",
                    title_align="left",
                    border_style="cyan",
                )
            )
        elif kind == "tool_use":
            name = event["name"]
            args = _format_tool_input(event["input"])
            console.print(
                Text.assemble(
                    ("→ ", "yellow"),
                    ("tool_use ", "bold yellow"),
                    (f"iter {i}  ", "dim"),
                    (name, "bold"),
                    ("(", "dim"),
                    (args, ""),
                    (")", "dim"),
                )
            )
        elif kind == "tool_result":
            output = _truncate(event["output"], TOOL_RESULT_PREVIEW_CHARS)
            console.print(
                Panel(
                    Text(output, style="dim"),
                    title=f"[yellow]tool_result[/]  [dim]iter {i}[/]",
                    title_align="left",
                    border_style="yellow",
                )
            )
        elif kind == "wait":
            console.print(
                Text.assemble(
                    ("✓ ", "green"),
                    ("wait", "bold green"),
                    (f"  iter {i} — cycle complete", "dim"),
                )
            )
    return render


def _print_banner(console: Console) -> None:
    console.print(
        Panel(
            Group(
                Text("rich-senpai · interactive trading agent", style="bold cyan"),
                Text("type /help for commands · Ctrl+D to exit", style="dim"),
            ),
            border_style="cyan",
        )
    )


HELP_TEXT = """\
[bold]commands[/]
  [bold]/help[/]    show this help
  [bold]/clear[/]   reset the in-session message history (short_memory.md is untouched)
  [bold]/quit[/]    exit (Ctrl+D works too)

[bold]everything else[/] is sent to the agent as the next user turn."""


def main() -> None:
    console = Console()
    _print_banner(console)

    session = PromptSession(history=FileHistory(str(HISTORY_PATH)))
    on_event = make_event_renderer(console)
    agent = AgentCore(on_event=on_event)
    messages: list[dict[str, Any]] = []
    turn_no = 0

    try:
        while True:
            try:
                user_input = session.prompt(HTML("\n<ansibrightmagenta>>>></ansibrightmagenta> "))
            except EOFError:
                console.print("[dim]bye.[/]")
                return
            except KeyboardInterrupt:
                console.print("[dim](Ctrl+C — type /quit to exit)[/]")
                continue

            user_input = user_input.strip()
            if not user_input:
                continue

            if user_input in {"/quit", "/exit"}:
                console.print("[dim]bye.[/]")
                return
            if user_input == "/help":
                console.print(Panel(HELP_TEXT, border_style="dim"))
                continue
            if user_input == "/clear":
                messages.clear()
                turn_no = 0
                console.print("[dim]history cleared. next turn will re-read short_memory.md[/]")
                continue

            turn_no += 1
            try:
                result = agent.run_turn(messages, user_input)
            except KeyboardInterrupt:
                console.print("[bold red]interrupted mid-cycle.[/] message history preserved.")
                continue
            except Exception as exc:
                console.print(f"[bold red]error:[/] {exc!r}")
                continue

            usage = result.usage or {}
            console.print(
                Text.assemble(
                    (f"\n#{turn_no}  ", "dim"),
                    (f"stop={result.stop_reason}  ", "bold"),
                    (f"iters={result.iterations}  ", ""),
                    (f"tok in={usage.get('input_tokens', 0)} out={usage.get('output_tokens', 0)}", "dim"),
                )
            )
    finally:
        agent.close()
