# Per-agent read-tracker for file_access tools.
#
# Mirrors Claude Code's "must read before edit" guard. Each agent run
# installs a fresh ReadTracker via set_tracker(); read_file marks files
# as seen, edit_file/write_file (overwrite) refuse if the path is not in
# the tracker.
#
# Tools call get_tracker() lazily — when no tracker is installed (direct
# tests, scripts), the guard becomes a no-op so callers don't need
# harness setup just to use the tools.

from __future__ import annotations

from contextvars import ContextVar, Token
from pathlib import Path


class ReadTracker:
    """Per-conversation set of files the agent has called read_file on."""

    def __init__(self) -> None:
        self._read: set[Path] = set()

    def mark_read(self, path: Path) -> None:
        self._read.add(path.resolve())

    def was_read(self, path: Path) -> bool:
        return path.resolve() in self._read

    def clear(self) -> None:
        self._read.clear()


_current: ContextVar["ReadTracker | None"] = ContextVar(
    "rich_senpai_file_access_tracker", default=None
)


def get_tracker() -> "ReadTracker | None":
    """Return the tracker for the current async context, or None."""
    return _current.get()


def set_tracker(tracker: "ReadTracker | None") -> Token:
    """Install *tracker* as the current tracker. Returns a token the
    caller can pass to reset_tracker() to restore the previous value
    (mandatory for nested agents)."""
    return _current.set(tracker)


def reset_tracker(token: Token) -> None:
    _current.reset(token)
