"""Message bus + plan/shutdown registries (s_full.py s09/s10).

Each agent (lead and any teammate) has a per-name JSONL inbox at
.team/inbox/<name>.jsonl. Senders append; readers drain. The plan and
shutdown registries are module-level dicts keyed by request_id so
callers can correlate responses to outstanding requests.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from core import config


VALID_MSG_TYPES = {
    "message",
    "broadcast",
    "shutdown_request",
    "shutdown_response",
    "plan_approval_request",
    "plan_approval_response",
}


class MessageBus:
    def __init__(self, inbox_dir: Path | None = None) -> None:
        self.inbox_dir = inbox_dir or config.INBOX_DIR
        self.inbox_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        return self.inbox_dir / f"{name}.jsonl"

    def send(
        self,
        sender: str,
        to: str,
        content: str,
        msg_type: str = "message",
        extra: dict[str, Any] | None = None,
    ) -> str:
        msg: dict[str, Any] = {
            "type": msg_type,
            "from": sender,
            "content": content,
            "timestamp": time.time(),
        }
        if extra:
            msg.update(extra)
        with self._path(to).open("a", encoding="utf-8") as f:
            f.write(json.dumps(msg) + "\n")
        return f"Sent {msg_type} to {to}"

    def read_inbox(self, name: str) -> list[dict[str, Any]]:
        path = self._path(name)
        if not path.exists():
            return []
        msgs = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").strip().splitlines()
            if line
        ]
        path.write_text("", encoding="utf-8")
        return msgs

    def broadcast(self, sender: str, content: str, names: list[str]) -> str:
        count = 0
        for n in names:
            if n != sender:
                self.send(sender, n, content, "broadcast")
                count += 1
        return f"Broadcast to {count} teammates"


# Module-level registries — shared between lead and teammate threads.
shutdown_requests: dict[str, dict[str, Any]] = {}
plan_requests: dict[str, dict[str, Any]] = {}


def new_request_id() -> str:
    return str(uuid.uuid4())[:8]
