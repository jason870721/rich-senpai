"""Custom Textual widgets used by the Senpai TUI."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from textual import events
from textual.binding import Binding
from textual.message import Message
from textual.widgets import TextArea


# A paste is "large" — and gets collapsed to a marker — when it crosses
# either of these thresholds. Tuned to be generous for typical
# command-line pastes (a path, a short snippet) while collapsing
# anything that would inflate the visible input area.
_PASTE_CHAR_THRESHOLD = 200
_PASTE_LINE_THRESHOLD = 4


class HistoryInput(TextArea):
    """Multi-line text input with submit-on-enter, shift+enter newline,
    and a persistent file-backed history navigated via ctrl+up / ctrl+down.

    Drop-in for Textual's single-line ``Input``:

      * Plain Enter posts a ``HistoryInput.Submitted(value=...)`` event;
        the host App is responsible for clearing the buffer
        (``widget.text = ""``).
      * Shift+Enter inserts a literal newline at the cursor.
      * Pastes that are short and few-line drop in verbatim; pastes
        that exceed ``_PASTE_CHAR_THRESHOLD`` characters or
        ``_PASTE_LINE_THRESHOLD`` lines are collapsed to a single-line
        marker like ``[paste #1: 4000 chars, 50 lines]``. The original
        text is stashed and re-substituted on submit, so the agent
        receives the full content while the visible input area stays
        a fixed three-to-six rows tall.
      * Ctrl+Up / Ctrl+Down walk the persisted history. Newlines in
        history entries are encoded as the literal ``\\n`` so each
        entry stays on a single line in the history file.
      * ``value`` is a read/write alias for ``text`` so callers written
        against the old ``Input`` API keep working.
    """

    class Submitted(Message):
        """Posted when the user hits plain Enter on a non-empty buffer."""

        def __init__(self, widget: "HistoryInput", value: str) -> None:
            super().__init__()
            self.widget = widget
            self.value = value

        @property
        def control(self) -> "HistoryInput":
            return self.widget

    BINDINGS = [
        # priority=True so plain Enter submits before TextArea's default
        # enter handler (which would otherwise insert a newline).
        Binding("enter", "submit_input", "submit", priority=True, show=False),
        Binding("shift+enter", "newline_at_cursor", "newline", show=False),
        Binding("ctrl+up", "history_prev", "prev", show=False),
        Binding("ctrl+down", "history_next", "next", show=False),
    ]

    def __init__(
        self,
        *args: Any,
        history_path: Path | None = None,
        placeholder: str = "",  # accepted for API compat, TextArea has no placeholder
        id: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, id=id, **kwargs)
        # `placeholder` is dropped — TextArea has no native placeholder
        # support. The TUI shows the hint in a sibling Static above the
        # input area instead.
        self._history_path = history_path
        self._history: list[str] = []
        self._idx: int | None = None
        # marker -> original pasted text. Populated by `_on_paste` when
        # a large paste arrives, drained by `expanded_text()` on submit
        # and cleared by `clear_buffer()` after the value is consumed.
        self._paste_stash: dict[str, str] = {}
        if history_path and history_path.exists():
            try:
                self._history = [
                    line for line in history_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
            except OSError:
                pass

    # ----- old-Input API shims ----------------------------------------------

    @property
    def value(self) -> str:
        return self.text

    @value.setter
    def value(self, v: str) -> None:
        self.load_text(v)
        self.move_cursor(self.document.end)

    # ----- history --------------------------------------------------------

    def push_history(self, text: str) -> None:
        if not text or not text.strip():
            return
        if not self._history or self._history[-1] != text:
            self._history.append(text)
            if self._history_path is not None:
                try:
                    with self._history_path.open("a", encoding="utf-8") as f:
                        # Encode newlines so multi-line entries don't
                        # split into multiple history records.
                        f.write(text.replace("\n", "\\n") + "\n")
                except OSError:
                    pass
        self._idx = None

    # ----- paste handling -------------------------------------------------

    def _on_paste(self, event: events.Paste) -> None:
        """Intercept pastes that are long or multi-line and substitute
        a single-line marker in the visible buffer. The original text
        is stashed and re-substituted on submit. Small pastes drop in
        verbatim so single-path pastes / one-liners aren't disrupted."""
        text = event.text
        line_count = text.count("\n") + 1
        if line_count < _PASTE_LINE_THRESHOLD and len(text) < _PASTE_CHAR_THRESHOLD:
            self.insert(text)
        else:
            marker = self._make_paste_marker(text, line_count)
            self._paste_stash[marker] = text
            self.insert(marker)
        event.stop()
        event.prevent_default()

    def _make_paste_marker(self, text: str, line_count: int) -> str:
        n = len(self._paste_stash) + 1
        return f"[paste #{n}: {len(text)} chars, {line_count} lines]"

    def expanded_text(self) -> str:
        """Return the buffer with every paste marker replaced by the
        original pasted text. Used by ``action_submit_input`` so the
        agent receives the full content the user pasted."""
        text = self.text
        for marker, real in self._paste_stash.items():
            text = text.replace(marker, real)
        return text

    def clear_buffer(self) -> None:
        """Reset the input — clears both the visible text and the
        paste-marker stash. Call after a successful submit."""
        self._paste_stash.clear()
        self.load_text("")

    # ----- bound actions --------------------------------------------------

    def action_submit_input(self) -> None:
        expanded = self.expanded_text()
        # Always fire — the host handles empty input appropriately
        # (e.g. the max_iterations continuation prompt resumes on
        # empty Enter, and non-empty fall through to a fresh turn).
        self.post_message(self.Submitted(self, expanded))

    def action_newline_at_cursor(self) -> None:
        self.insert("\n")

    def action_history_prev(self) -> None:
        if not self._history:
            return
        self._idx = (
            len(self._history) - 1 if self._idx is None else max(0, self._idx - 1)
        )
        decoded = self._history[self._idx].replace("\\n", "\n")
        self.load_text(decoded)
        self.move_cursor(self.document.end)

    def action_history_next(self) -> None:
        if self._idx is None:
            return
        self._idx += 1
        if self._idx >= len(self._history):
            self._idx = None
            self.load_text("")
        else:
            decoded = self._history[self._idx].replace("\\n", "\n")
            self.load_text(decoded)
            self.move_cursor(self.document.end)
