"""File-backed task board (s_full.py s07 mechanism).

Each task is a JSON document at .tasks/task_<id>.json. The board is shared
between the lead agent and any spawned teammates so work survives process
restarts and can be picked up by whoever is idle. Status moves
pending -> in_progress -> completed (or deleted to remove).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core import config


class TaskManager:
    def __init__(self, tasks_dir: Path | None = None) -> None:
        self.tasks_dir = tasks_dir or config.TASKS_DIR
        self.tasks_dir.mkdir(parents=True, exist_ok=True)

    def _next_id(self) -> int:
        ids = [int(f.stem.split("_")[1]) for f in self.tasks_dir.glob("task_*.json")]
        return max(ids, default=0) + 1

    def _path(self, tid: int) -> Path:
        return self.tasks_dir / f"task_{tid}.json"

    def _load(self, tid: int) -> dict[str, Any]:
        p = self._path(tid)
        if not p.exists():
            raise ValueError(f"Task {tid} not found")
        return json.loads(p.read_text(encoding="utf-8"))

    def _save(self, task: dict[str, Any]) -> None:
        self._path(task["id"]).write_text(json.dumps(task, indent=2), encoding="utf-8")

    def create(self, subject: str, description: str = "") -> str:
        task = {
            "id": self._next_id(),
            "subject": subject,
            "description": description,
            "status": "pending",
            "owner": None,
            "blockedBy": [],
        }
        self._save(task)
        return json.dumps(task, indent=2)

    def get(self, tid: int) -> str:
        return json.dumps(self._load(tid), indent=2)

    def update(
        self,
        tid: int,
        status: str | None = None,
        add_blocked_by: list[int] | None = None,
        remove_blocked_by: list[int] | None = None,
    ) -> str:
        task = self._load(tid)
        if status:
            task["status"] = status
            if status == "completed":
                # cascade: remove this id from anyone else's blockedBy list
                for f in self.tasks_dir.glob("task_*.json"):
                    other = json.loads(f.read_text(encoding="utf-8"))
                    if tid in other.get("blockedBy", []):
                        other["blockedBy"].remove(tid)
                        self._save(other)
            if status == "deleted":
                self._path(tid).unlink(missing_ok=True)
                return f"Task {tid} deleted"
        if add_blocked_by:
            task["blockedBy"] = sorted(set(task.get("blockedBy", []) + list(add_blocked_by)))
        if remove_blocked_by:
            task["blockedBy"] = [x for x in task.get("blockedBy", []) if x not in remove_blocked_by]
        self._save(task)
        return json.dumps(task, indent=2)

    def list_all(self) -> str:
        tasks = [
            json.loads(f.read_text(encoding="utf-8"))
            for f in sorted(self.tasks_dir.glob("task_*.json"))
        ]
        if not tasks:
            return "No tasks."
        glyphs = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}
        lines: list[str] = []
        for t in tasks:
            mark = glyphs.get(t["status"], "[?]")
            owner = f" @{t['owner']}" if t.get("owner") else ""
            blocked = f" (blocked by: {t['blockedBy']})" if t.get("blockedBy") else ""
            lines.append(f"{mark} #{t['id']}: {t['subject']}{owner}{blocked}")
        return "\n".join(lines)

    def claim(self, tid: int, owner: str) -> str:
        task = self._load(tid)
        task["owner"] = owner
        task["status"] = "in_progress"
        self._save(task)
        return f"Claimed task #{tid} for {owner}"

    def list_unclaimed(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for f in sorted(self.tasks_dir.glob("task_*.json")):
            t = json.loads(f.read_text(encoding="utf-8"))
            if t.get("status") == "pending" and not t.get("owner") and not t.get("blockedBy"):
                out.append(t)
        return out
