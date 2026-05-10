"""In-memory todo list (s_full.py s03 mechanism).

Lives in process memory only — gets reset whenever AgentCore is rebuilt.
For durable cross-session work use core.tasks_file.TaskManager instead.
"""
from __future__ import annotations

from typing import Any


_VALID_STATUS = ("pending", "in_progress", "completed")
_MAX_ITEMS = 20


class TodoManager:
    def __init__(self) -> None:
        self.items: list[dict[str, str]] = []

    def update(self, items: list[dict[str, Any]]) -> str:
        validated: list[dict[str, str]] = []
        in_progress = 0
        for i, item in enumerate(items):
            content = str(item.get("content", "")).strip()
            status = str(item.get("status", "pending")).lower()
            active_form = str(item.get("activeForm", "")).strip()
            if not content:
                raise ValueError(f"Item {i}: content required")
            if status not in _VALID_STATUS:
                raise ValueError(f"Item {i}: invalid status '{status}'")
            if not active_form:
                raise ValueError(f"Item {i}: activeForm required")
            if status == "in_progress":
                in_progress += 1
            validated.append({"content": content, "status": status, "activeForm": active_form})
        if len(validated) > _MAX_ITEMS:
            raise ValueError(f"Max {_MAX_ITEMS} todos")
        if in_progress > 1:
            raise ValueError("Only one in_progress allowed")
        self.items = validated
        return self.render()

    def render(self) -> str:
        if not self.items:
            return "No todos."
        glyphs = {"completed": "[x]", "in_progress": "[>]", "pending": "[ ]"}
        lines: list[str] = []
        for item in self.items:
            mark = glyphs.get(item["status"], "[?]")
            suffix = f" <- {item['activeForm']}" if item["status"] == "in_progress" else ""
            lines.append(f"{mark} {item['content']}{suffix}")
        done = sum(1 for t in self.items if t["status"] == "completed")
        lines.append(f"\n({done}/{len(self.items)} completed)")
        return "\n".join(lines)

    def has_open_items(self) -> bool:
        return any(item.get("status") != "completed" for item in self.items)

    def reset(self):
        self.items: list[dict[str, str]] = []
