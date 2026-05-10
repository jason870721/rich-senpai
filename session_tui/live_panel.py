"""LivePanel — shared scaffold for docked, live-updated status panels.

The TUI hosts several panels that share the same lifecycle:

  1. Pull a snapshot from a singleton state source.
  2. Hide the docked widget when the snapshot is empty.
  3. While there is work in flight, repaint the docked widget in place.
  4. The instant everything settles, archive the final snapshot into the
     scrolling log (once per signature) and hide the docked widget.

`TodoWrite` and `background_run` are the first two consumers; future
status-board tools (e.g. teammate roster, claim queue) drop in by
subclassing `LivePanel` and supplying:

  * ``snapshot``     — pull current items from the source of truth
  * ``signature``    — hashable identity for archive / dedupe
  * ``all_settled``  — when True, archive + hide
  * ``build_body``   — render the items as a Rich ``Text``
  * ``header_meta``  — short summary string shown next to the title

The visual design (glyph + accent + title + meta + body) is intentionally
parameterised on the constructor so each panel keeps its own look.
"""
from __future__ import annotations

from typing import Any, Generic, Hashable, Protocol, TypeVar

from rich.console import Group
from rich.text import Text
from textual.widgets import Static

from session_tui.render import block
from session_tui.style import OK


T = TypeVar("T")
Sig = tuple  # signature is always a hashable tuple


class _AppLike(Protocol):
    def write(self, renderable: Any) -> None: ...
    def query_one(self, selector: str, expect_type: type) -> Any: ...


class LivePanel(Generic[T]):
    """Base class for docked panels with archive-on-settle behaviour.

    Subclasses override the four hook methods; the ``refresh`` orchestration
    is implemented once here.
    """

    def __init__(
        self,
        *,
        widget_id: str,
        glyph: str,
        accent: str,
        title: str,
        done_accent: str = OK,
        skip_unchanged: bool = False,
    ) -> None:
        self.widget_id = widget_id
        self.glyph = glyph
        self.accent = accent
        self.title = title
        self.done_accent = done_accent
        # When True, refresh() short-circuits if the signature matches the
        # last paint. Use this for panels driven by a wall-clock tick (e.g.
        # background, polled at 1Hz). Event-driven panels can leave it off.
        self.skip_unchanged = skip_unchanged
        self._archived_signature: Sig | None = None
        self._last_signature: Sig | None = None

    # ----- subclass hooks --------------------------------------------------

    def snapshot(self) -> list[T]:
        """Return the current items from the source of truth."""
        raise NotImplementedError

    def signature(self, items: list[T]) -> Sig:
        """Stable identity for ``items`` — used for archive dedupe."""
        raise NotImplementedError

    def all_settled(self, items: list[T]) -> bool:
        """True when there is no pending / running work in ``items``.

        Returning True triggers a one-time archive into the scrolling log
        and hides the docked widget."""
        raise NotImplementedError

    def build_body(self, items: list[T]) -> Text:
        """Format ``items`` as the panel body (multi-line ``Text``)."""
        raise NotImplementedError

    def header_meta(self, items: list[T]) -> str:
        """Short status string appended after the title (e.g. '3/5')."""
        return ""

    def on_archive(self, app: _AppLike) -> None:
        """Hook fired after an all-settled archive is committed. Used by
        TodosPanel to reset its 'tool_use already announced' flag so the
        next round re-announces."""

    # ----- shared template -------------------------------------------------

    def reset(self) -> None:
        """Clear dedupe state — invoked from /clear."""
        self._archived_signature = None
        self._last_signature = None

    def build(
        self,
        items: list[T],
        *,
        override_title: str | None = None,
        override_accent: str | None = None,
    ) -> Group:
        """Render the full panel (header line + body) as a Rich group."""
        title = override_title if override_title is not None else self.title
        accent = override_accent if override_accent is not None else self.accent
        meta = self.header_meta(items)
        header = Text()
        header.append(title, style=f"bold {accent}")
        if meta:
            header.append(f"   {meta}", style="dim")
        return block(self.glyph, accent, header, self.build_body(items))

    def refresh(self, app: _AppLike) -> None:
        """Repaint (or hide / archive) the docked widget from the latest
        snapshot. Idempotent — safe to call from a tick or an event."""
        widget = app.query_one(f"#{self.widget_id}", Static)
        items = self.snapshot()

        if not items:
            widget.display = False
            widget.update("")
            self._last_signature = None
            return

        sig = self.signature(items)
        if self.skip_unchanged and sig == self._last_signature:
            return
        self._last_signature = sig

        if self.all_settled(items):
            if sig != self._archived_signature:
                app.write(
                    self.build(
                        items,
                        override_title=f"{self.title} · all done",
                        override_accent=self.done_accent,
                    )
                )
                self._archived_signature = sig
            widget.display = False
            widget.update("")
            self.on_archive(app)
            return

        # Mixed / pending — clear any stale archive marker so the next
        # all-settled snapshot re-archives cleanly.
        self._archived_signature = None
        widget.display = True
        widget.update(self.build(items))
