"""Textual REPL package for rich-senpai.

Public surface:

    from session_tui import main, SenpaiApp

The submodules — ``tui``, ``events``, ``panels``, ``render``,
``commands``, ``clipboard``, ``style``, ``widgets``, ``welcome``,
``live_panel`` — are organised by concern and stable to import
directly when needed.
"""
from session_tui.tui import SenpaiApp, main


__all__ = ["SenpaiApp", "main"]
