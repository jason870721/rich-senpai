"""Custom Textual widgets used by the Senpai TUI."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.binding import Binding
from textual.widgets import Input


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
