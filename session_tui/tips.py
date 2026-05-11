"""Rotating tips shown in the idle placeholder above the input.

The TUI displays one tip at a time in the `#input_hint` row, rotating
through this list every ``ROTATION_SECONDS`` while the user has nothing
typed and the agent is not looping. As soon as the user starts typing,
or the agent enters a turn, the hint row is cleared — the tips return
when both go idle again.

When you ship a new feature worth surfacing, add a single-line tip to
``TIPS``. Keep entries short — they share one row with the slash-command
list and the keymap hints. The cap is ten entries; the assertion at
module load enforces it.
"""
from __future__ import annotations

from session_tui.commands import placeholder_summary


ROTATION_SECONDS: float = 10.0
MAX_TIPS: int = 10

TIPS: list[str] = [
    # First slot is auto-derived from the slash-command registry so the
    # rotation stays in sync when commands are added or removed.
    placeholder_summary(),
    "Type '/{skill-name}' at begin to active your customized skill with following conversation.",
    "Add your customized skill to the skill folder: .senpai/skills/{skill-name}/SKILL.md",
    "Type '/help' to see what each slash command does.",
    "To avoid context too long, you can use the '/compact' tp compress current context.",
]


assert len(TIPS) <= MAX_TIPS, (
    f"tips.TIPS has {len(TIPS)} entries — cap is {MAX_TIPS}; "
    "remove or merge one before adding more."
)


def tip_at(index: int) -> str:
    """Return the tip at ``index`` modulo the list length.

    Safe when ``TIPS`` is empty — returns an empty string so callers
    can update the hint widget without a branch."""
    if not TIPS:
        return ""
    return "💡 : " + TIPS[index % len(TIPS)]
