"""Welcome panel rendering — the intro splash with banner + greeting."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.align import Align
from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from rich_senpai.session_tui.style import ACCENT, BRAND, GOLD, SUBTLE


BANNER_PATH = Path(__file__).parent / "assets" / "banner.txt"


def _load_banner() -> Text:
    """Read the ASCII banner once per render and style it gold."""
    raw = BANNER_PATH.read_text(encoding="utf-8").rstrip("\n")
    return Text(raw, style=f"bold {GOLD}", no_wrap=True, overflow="crop")


def paint_welcome(write: callable, model_label: str) -> None:
    """Render the full-width intro panel into the log via `write`.

    The gold ASCII banner sits on top, with the greeting + capability
    list and session metadata stacked beneath it. Called from on_mount
    and from /clear so a freshly reset screen still shows the brand
    + bindings.
    """
    banner = Align.center(_load_banner())

    greeting = Text()
    greeting.append("welcome back  ·  ", style=f"bold {ACCENT}")
    greeting.append("ready when you are!\n\n", style=ACCENT)
    greeting.append(
        "I am rich-senpai, your autonomous coding agent.\n\n"
        "I'm here to help you solve problems and build software.\n\n",
        style="white",
    )
    for bullet in (
        "Using /{skill-name} to activate your customized skill (in .senpai/skills)",
        "Background tasks & Inbox-Driven coordination",
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

    body = Group(banner, Text(""), greeting)

    write(
        Panel(
            body,
            title=f"[bold {BRAND}]✻ rich-senpai[/]",
            title_align="left",
            border_style=BRAND,
            padding=(1, 2),
        )
    )
    write(Text(""))
