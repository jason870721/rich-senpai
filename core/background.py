"""Background command runner (s_full.py s08 mechanism).

Fire-and-forget shell commands. Each call returns a short task id; the
agent can `check_background(task_id)` later, and finished tasks also push
a completion notification onto a queue that the agent loop drains before
each LLM call so the model sees them without polling.

`self.tasks` is mutated from worker threads (`_exec`) and read from the
agent thread (`check`, `drain`). All accesses go through `self._lock`
so a "lookup-then-update" sequence is atomic.
"""
from __future__ import annotations

import subprocess
import threading
import uuid
from pathlib import Path
from queue import Queue
from typing import Any

from core import config
from core.config import BG_DEFAULT_TIMEOUT


_RESULT_MAX_CHARS = 50_000
_SNAPSHOT_PREVIEW_CHARS = 500


def _truncate_with_marker(text: str, limit: int, *, suffix_hint: str) -> str:
    if len(text) <= limit:
        return text
    extra = len(text) - limit
    return f"{text[:limit]}\n... (+{extra} more chars{suffix_hint})"


class BackgroundManager:
    def __init__(self, workdir: Path | None = None) -> None:
        self.workdir = workdir or config.WORKDIR
        self.tasks: dict[str, dict[str, Any]] = {}
        self.notifications: Queue[dict[str, Any]] = Queue()
        self._lock = threading.Lock()

    def run(self, command: str, timeout: int = BG_DEFAULT_TIMEOUT) -> str:
        tid = str(uuid.uuid4())[:8]
        with self._lock:
            self.tasks[tid] = {"status": "running", "command": command, "result": None}
        threading.Thread(
            target=self._exec,
            args=(tid, command, timeout),
            daemon=True,
        ).start()
        return f"task_id={tid}\nstarted: {command[:80]}"

    def _exec(self, tid: str, command: str, timeout: int) -> None:
        try:
            r = subprocess.run(
                command,
                shell=True,
                cwd=self.workdir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            raw = (r.stdout + r.stderr).strip()
            output = _truncate_with_marker(
                raw, _RESULT_MAX_CHARS, suffix_hint=" elided"
            )
            status, result = "completed", output or "(no output)"
        except subprocess.TimeoutExpired:
            status, result = "error", f"timeout after {timeout}s"
        except Exception as exc:  # noqa: BLE001 -- want everything in result
            status, result = "error", str(exc)

        preview = _truncate_with_marker(
            str(result),
            _SNAPSHOT_PREVIEW_CHARS,
            suffix_hint=f", call check_background('{tid}') for full output",
        )

        with self._lock:
            self.tasks[tid].update({"status": status, "result": result})
            snapshot = {
                "task_id": tid,
                "status": status,
                "result": preview,
            }
        self.notifications.put(snapshot)

    def check(self, tid: str | None = None) -> str:
        with self._lock:
            if tid:
                t = self.tasks.get(tid)
                if not t:
                    return f"Unknown background task: {tid}"
                command = t.get("command", "")
                result = t.get("result") or "(running)"
                return f"[{t['status']}] $ {command}\n{result}"
            if not self.tasks:
                return "No bg tasks."
            # Snapshot to a list of tuples while holding the lock so the join
            # below doesn't iterate a dict that another thread is mutating.
            items = [(k, v["status"], v["command"][:60]) for k, v in self.tasks.items()]
        return "\n".join(f"{k}: [{s}] {c}" for k, s, c in items)

    def drain(self) -> list[dict[str, Any]]:
        notifs: list[dict[str, Any]] = []
        while not self.notifications.empty():
            notifs.append(self.notifications.get_nowait())
        return notifs
