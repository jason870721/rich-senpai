"""Welcome panel rendering — the intro splash with greeting + pyramid."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from session_tui.style import ACCENT, BRAND, GOLD, SUBTLE


def paint_welcome(write: callable, model_label: str) -> None:
    """Render the full-width intro panel into the log via `write`.

    Two columns: greeting + capability list on the left, gold pyramid
    logo on the right. Called from on_mount and from /clear so a freshly
    reset screen still shows the brand + bindings.
    """
    greeting = Text()
    greeting.append("welcome back  ·  ", style=f"bold {ACCENT}")
    greeting.append("ready when you are!\n\n", style=ACCENT)
    greeting.append(
        "I am interactive trading agent - rich senpai \n\n"
        "skills, tools, todos, teammates, and a persistent\n"
        "short-memory scratchpad shared across sessions.\n\n",
        style="white",
    )
    for bullet in (
        "persistent short memory survives across turns",
        "background tasks & inbox-driven coordination",
    ):
        greeting.append("  ⌁  ", style=GOLD)
        greeting.append(bullet + "\n", style="white")
    greeting.append("\n")
    greeting.append("model    · ", style="dim")
    greeting.append(model_label + "\n", style=SUBTLE)
    greeting.append("session  · ", style="dim")
    greeting.append(
        datetime.now().strftime("%Y-%m-%d %H:%M"), style=SUBTLE
    )
    greeting.append("\n\n")
    greeting.append(
        "/help  ·  /clear  ·  Esc to interrupt  ·  !q to exit",
        style="dim",
    )

    # Pre-padded so every row has the apex at column 6 of 13 — keeps
    # the pyramid centered no matter how its column is justified.
    # Gradient: bright at the apex, dimming toward the base.
    pyramid = Text()
    for i, (line, style) in enumerate([
        ("      ▲      ", f"bold {GOLD}"),
        ("     ▲▲▲     ", f"bold {GOLD}"),
        ("     ▲▲▲▲▲    ", GOLD),
        ("     ▲▲▲▲▲▲▲   ", GOLD),
        ("     ▲▲▲▲▲▲▲▲▲  ", "gold3"),
        ("     ▲▲▲▲▲▲▲▲▲▲▲ ", "gold3"),
    ]):
        if i:
            pyramid.append("\n")
        pyramid.append(line, style=style)

    grid = Table.grid(expand=True, padding=(0, 2))
    grid.add_column(ratio=3)
    grid.add_column(ratio=1, justify="center")
    grid.add_row(greeting, pyramid)

    write(
        Panel(
            grid,
            title=f"[bold {BRAND}]✻ rich-senpai[/]",
            title_align="left",
            border_style=BRAND,
            padding=(1, 2),
        )
    )
    write(Text(""))
