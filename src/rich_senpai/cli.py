"""Console entrypoint for ``rich-senpai``.

Wires `.env`, file-based logging, and the Textual TUI in that order.
Heavy imports happen inside ``main()`` so importing this module (e.g.
from tests) is side-effect-free.
"""
from __future__ import annotations


def main() -> None:
    """Load env, configure logging, launch the TUI."""
    from dotenv import load_dotenv

    load_dotenv()

    # Configure logging before any project module imports — child loggers
    # (`rich_senpai.*`) created during import will then inherit the level
    # and FileHandler set up here.
    from rich_senpai.core.logging_setup import setup_logging

    setup_logging()

    from rich_senpai.session_tui.tui import main as tui_main

    tui_main()


if __name__ == "__main__":
    main()
