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
# `/quit` itself is a registered slash command (see session_tui.commands); the
# extra spellings here are convenience shortcuts that bypass dispatch.
QUIT_ALIASES = frozenset({"/exit", "exit", "quit", "!q"})
