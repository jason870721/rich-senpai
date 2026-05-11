"""Slash-command registry.

Each command is a free function ``cmd_xxx(app)`` that mutates the
``SenpaiApp`` it's handed. The ``COMMANDS`` dict maps the user-typed
alias (`/help`, `/clear`, …) to the handler. ``dispatch(app, alias)``
returns True iff the alias matched and the handler ran.

Adding a command:

  1. Write ``def cmd_foo(app: SenpaiApp) -> None: ...``
  2. Append a ``Command("/foo", "<one-line summary>", cmd_foo)`` entry.

The summaries flow into the ``/help`` body so the help text never falls
out of date with the registry.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, TYPE_CHECKING

from rich.text import Text

from rich_senpai.core import state
from rich_senpai.session_tui.clipboard import copy_to_clipboard
from rich_senpai.session_tui.render import block
from rich_senpai.session_tui.style import ACCENT, BRAND


if TYPE_CHECKING:
    from rich_senpai.session_tui.tui import SenpaiApp


@dataclass(frozen=True)
class Command:
    alias: str
    summary: str
    handler: Callable[["SenpaiApp"], None]


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def cmd_help(app: "SenpaiApp") -> None:
    header = Text("commands", style=f"bold {BRAND}")
    lines: list[Text] = []
    for cmd in COMMANDS:
        line = Text()
        line.append(f"  {cmd.alias:<10}", style=f"bold {BRAND}")
        line.append(cmd.summary, style="white")
        lines.append(line)
    body = Text("\n").join(lines)
    body.append("\n\n")
    body.append("input: ", style="bold")
    body.append(
        "Enter submit · Shift+Enter newline · Ctrl+↑/↓ history · Esc interrupt\n",
    )
    body.append(
        "copy from log: hold Shift while click-dragging to bypass mouse "
        "capture; Cmd-C / Ctrl-Shift-C in the terminal then copies. "
        "/copy is the keyboard alternative for the last reply.\n",
        style="dim",
    )
    body.append("\nany other text is sent to the agent as the next user turn.", style="dim")
    app.write(block("✦", BRAND, header, body))


def cmd_clear(app: "SenpaiApp") -> None:
    app.action_clear_history()


def cmd_compact(app: "SenpaiApp") -> None:
    app.compact_history()


def cmd_tasks(app: "SenpaiApp") -> None:
    header = Text("tasks", style=f"bold {ACCENT}")
    app.write(block("✦", ACCENT, header, Text(state.TASK_MGR.list_all())))


def cmd_team(app: "SenpaiApp") -> None:
    header = Text("team", style=f"bold {ACCENT}")
    app.write(block("✦", ACCENT, header, Text(state.get_team().list_all())))


def cmd_inbox(app: "SenpaiApp") -> None:
    inbox = state.BUS.read_inbox(state.LEAD_NAME)
    body = json.dumps(inbox, indent=2) if inbox else "(empty)"
    header = Text("inbox", style=f"bold {ACCENT}")
    app.write(block("✦", ACCENT, header, Text(body)))


def cmd_quit(app: "SenpaiApp") -> None:
    app.exit()


def cmd_copy(app: "SenpaiApp") -> None:
    text = app.last_assistant_text
    if not text:
        app.write(Text("nothing to copy yet — send a message first.", style="dim"))
        return
    tool = copy_to_clipboard(text)
    if tool is None:
        app.write(
            Text(
                "no clipboard tool found. install pbcopy (macOS), wl-copy "
                "(Wayland), or xclip (X11), or hold shift while click-"
                "dragging in the log to use the terminal's native selection.",
                style="bold red",
            )
        )
        return
    app.write(
        Text(
            f"copied last reply ({len(text)} chars) via {tool}.",
            style="dim",
        )
    )


# ---------------------------------------------------------------------------
# Registry + dispatch
# ---------------------------------------------------------------------------


COMMANDS: tuple[Command, ...] = (
    Command("/help",    "show this help",                                                     cmd_help),
    Command("/clear",   "reset the in-session message history (short_memory.md is untouched)", cmd_clear),
    Command("/compact", "manually compress the in-session message history",                   cmd_compact),
    Command("/tasks",   "list every file-backed task",                                         cmd_tasks),
    Command("/team",    "list every spawned teammate",                                         cmd_team),
    Command("/inbox",   "drain the lead's inbox (visible to the user only)",                  cmd_inbox),
    Command("/copy",    "copy the last assistant reply to the system clipboard",              cmd_copy),
    Command("/quit",    "exit the session (Ctrl+Q works too)",                                cmd_quit),
)


_BY_ALIAS: dict[str, Command] = {c.alias: c for c in COMMANDS}


def dispatch(app: "SenpaiApp", alias: str) -> bool:
    """Run the handler bound to ``alias`` if it exists. Returns True iff
    the alias was recognised and handled."""
    cmd = _BY_ALIAS.get(alias)
    if cmd is None:
        return False
    cmd.handler(app)
    return True


def placeholder_summary() -> str:
    """One-line `· ` separated list of every alias — used as the empty-
    buffer hint above the input."""
    return " · ".join(c.alias for c in COMMANDS)
