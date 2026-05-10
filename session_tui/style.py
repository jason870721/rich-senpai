"""Palette, spinner, and chrome constants shared across the TUI modules.

Cyan = primary brand for dialogue and chrome; gold = active / in-progress
events (skill load, wait, compact, drains, interrupt warnings); soft green
= completed states; grey50 = execution metadata. Red is reserved strictly
for errors and exceptions.
"""
from __future__ import annotations

from pathlib import Path


# Palette
BRAND = "cyan"
ACCENT = "bright_cyan"
GOLD = "gold1"
SUBTLE = "grey50"
OK = "green3"
TOOL_USE = "orange3"  # alternatives: "magenta", "deep_pink3", "pink3"


# Spinner — 10 frames at 100ms = one revolution per second.
SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
SPINNER_INTERVAL = 0.1


# History + truncation
HISTORY_PATH = Path.home() / ".rich_senpai_history"
TOOL_RESULT_PREVIEW_CHARS = 800


# Quit aliases — typed in the input box, intercepted before the agent sees them.
QUIT_ALIASES = frozenset({"/quit", "/exit", "exit", "quit", "!q"})


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
