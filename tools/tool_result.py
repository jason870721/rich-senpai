"""Structured tool handler return value.

Lives in its own module so individual tool handlers (e.g. `tools.bash`)
can import `ToolResult` without pulling in `tools.tool_register`, which
imports every tool module at load time and would create a cycle.

Tools may return either a plain `str` (treated as a successful result)
or a `ToolResult` to flag failure. The dispatch layer in
`tools.tool_register` normalizes both shapes to `ToolResult` so callers
always have access to the success flag — the TUI uses it to colour
failed `tool_result` events red, while the LLM still receives `text`
as the `tool_result` content.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ToolResult:
    text: str
    ok: bool = True


def as_text(value: Any) -> str:
    """Coerce a tool handler return value to its display text. Used by
    dispatch paths that don't propagate the ok flag (subagent, teammate
    `_dispatch`); the lead's loop preserves it via `call_tool`."""
    if isinstance(value, ToolResult):
        return value.text
    return str(value)
