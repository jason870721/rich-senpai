"""Persistent autonomous teammates (s_full.py s09 + s11).

A teammate is a worker that runs its own ReAct loop in a daemon thread,
talks to the lead through MessageBus, claims work off the file-backed
TaskManager when idle, and obeys shutdown_request messages. Each
teammate's identity is re-injected if the message list ever shrinks
(e.g. after compaction) so it doesn't forget who it is.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from core import config
from core.config import TEAM_IDLE_TIMEOUT, TEAM_MAX_TOKENS, TEAM_POLL_INTERVAL
from core.llm import (
    LLMClient,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from core.messaging import MessageBus
from core.tasks_file import TaskManager
from tools import bash as bash_tool
from tools import edit_file as edit_file_tool
from tools import read_file as read_file_tool
from tools import write_file as write_file_tool


_TEAMMATE_TOOLS = [
    bash_tool.SPEC,
    read_file_tool.SPEC,
    write_file_tool.SPEC,
    edit_file_tool.SPEC,
    {
        "name": "send_message",
        "description": "Send a message to another teammate or the lead.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["to", "content"],
        },
    },
    {
        "name": "idle",
        "description": "Signal you have no more work and should idle.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "claim_task",
        "description": "Claim a pending task by id.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
    },
]


_FS_HANDLERS = {
    bash_tool.SPEC["name"]: bash_tool.bash,
    read_file_tool.SPEC["name"]: read_file_tool.read_file,
    write_file_tool.SPEC["name"]: write_file_tool.write_file,
    edit_file_tool.SPEC["name"]: edit_file_tool.edit_file,
}


class TeammateManager:
    def __init__(
        self,
        *,
        llm: LLMClient,
        bus: MessageBus,
        task_mgr: TaskManager,
        team_dir: Path | None = None,
    ) -> None:
        self.llm = llm
        self.bus = bus
        self.task_mgr = task_mgr
        self.team_dir = team_dir or config.TEAM_DIR
        self.team_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.team_dir / "config.json"
        self.config = self._load_config()
        self.threads: dict[str, threading.Thread] = {}

    def _load_config(self) -> dict[str, Any]:
        if self.config_path.exists():
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        return {"team_name": "default", "members": []}

    def _save_config(self) -> None:
        self.config_path.write_text(
            json.dumps(self.config, indent=2),
            encoding="utf-8",
        )

    def _find(self, name: str) -> dict[str, Any] | None:
        for m in self.config["members"]:
            if m["name"] == name:
                return m
        return None

    def _set_status(self, name: str, status: str) -> None:
        member = self._find(name)
        if member:
            member["status"] = status
            self._save_config()

    def member_names(self) -> list[str]:
        return [m["name"] for m in self.config["members"]]

    def list_all(self) -> str:
        if not self.config["members"]:
            return "No teammates."
        lines = [f"Team: {self.config['team_name']}"]
        for m in self.config["members"]:
            lines.append(f"  {m['name']} ({m['role']}): {m['status']}")
        return "\n".join(lines)

    def spawn(self, name: str, role: str, prompt: str) -> str:
        member = self._find(name)
        if member:
            if member["status"] not in ("idle", "shutdown"):
                return f"error: '{name}' is currently {member['status']}"
            member["status"] = "working"
            member["role"] = role
        else:
            member = {"name": name, "role": role, "status": "working"}
            self.config["members"].append(member)
        self._save_config()
        thread = threading.Thread(
            target=self._loop,
            args=(name, role, prompt),
            daemon=True,
        )
        self.threads[name] = thread
        thread.start()
        return f"Spawned '{name}' (role: {role})"

    def _loop(self, name: str, role: str, prompt: str) -> None:
        team_name = self.config["team_name"]
        workdir = config.WORKDIR
        sys_prompt = (
            f"You are '{name}', role: {role}, team: {team_name}, at {workdir}. "
            f"Use idle when done with current work. You may auto-claim tasks."
        )
        messages: list[Message] = [
            Message(role="user", content=[TextBlock(text=prompt)])
        ]

        while True:
            # ---- WORK PHASE -------------------------------------------------
            for _ in range(50):
                inbox = self.bus.read_inbox(name)
                shutdown = False
                for msg in inbox:
                    if msg.get("type") == "shutdown_request":
                        shutdown = True
                        break
                    messages.append(
                        Message(role="user", content=[TextBlock(text=json.dumps(msg))])
                    )
                if shutdown:
                    self._set_status(name, "shutdown")
                    return

                try:
                    response = self.llm.create_message(
                        messages=messages,
                        system=sys_prompt,
                        tools=_TEAMMATE_TOOLS,
                        max_tokens=TEAM_MAX_TOKENS,
                    )
                except Exception:  # noqa: BLE001 -- log via status, don't crash
                    self._set_status(name, "shutdown")
                    return

                messages.append(Message(role="assistant", content=list(response.content)))
                if response.stop_reason != "tool_use":
                    break

                results: list[ToolResultBlock] = []
                idle_requested = False
                for block in response.content:
                    if not isinstance(block, ToolUseBlock):
                        continue
                    output = self._dispatch(name, block.name, dict(block.input or {}))
                    if block.name == "idle":
                        idle_requested = True
                    print(f"  [{name}] {block.name}: {str(output)[:120]}")
                    results.append(ToolResultBlock(tool_use_id=block.id, content=str(output)))
                messages.append(Message(role="user", content=list(results)))
                if idle_requested:
                    break

            # ---- IDLE PHASE -------------------------------------------------
            self._set_status(name, "idle")
            resume = False
            for _ in range(max(TEAM_IDLE_TIMEOUT // TEAM_POLL_INTERVAL, 1)):
                time.sleep(TEAM_POLL_INTERVAL)
                inbox = self.bus.read_inbox(name)
                if inbox:
                    for msg in inbox:
                        if msg.get("type") == "shutdown_request":
                            self._set_status(name, "shutdown")
                            return
                        messages.append(
                            Message(role="user", content=[TextBlock(text=json.dumps(msg))])
                        )
                    resume = True
                    break

                unclaimed = self.task_mgr.list_unclaimed()
                if unclaimed:
                    task = unclaimed[0]
                    self.task_mgr.claim(task["id"], name)
                    if len(messages) <= 3:
                        # identity re-injection — context may have been compacted
                        messages.insert(
                            0,
                            Message(
                                role="user",
                                content=[
                                    TextBlock(
                                        text=f"<identity>You are '{name}', role: {role}, team: {team_name}.</identity>"
                                    )
                                ],
                            ),
                        )
                        messages.insert(
                            1,
                            Message(
                                role="assistant",
                                content=[TextBlock(text=f"I am {name}. Continuing.")],
                            ),
                        )
                    messages.append(
                        Message(
                            role="user",
                            content=[
                                TextBlock(
                                    text=(
                                        f"<auto-claimed>Task #{task['id']}: {task['subject']}\n"
                                        f"{task.get('description', '')}</auto-claimed>"
                                    )
                                )
                            ],
                        )
                    )
                    messages.append(
                        Message(
                            role="assistant",
                            content=[TextBlock(text=f"Claimed task #{task['id']}. Working on it.")],
                        )
                    )
                    resume = True
                    break

            if not resume:
                self._set_status(name, "shutdown")
                return
            self._set_status(name, "working")

    def _dispatch(self, name: str, tool_name: str, args: dict[str, Any]) -> str:
        if tool_name == "idle":
            return "Entering idle phase."
        if tool_name == "claim_task":
            try:
                return self.task_mgr.claim(int(args["task_id"]), name)
            except (KeyError, ValueError) as exc:
                return f"error: {exc}"
        if tool_name == "send_message":
            try:
                return self.bus.send(name, args["to"], args["content"])
            except KeyError as exc:
                return f"error: missing argument {exc}"
        handler = _FS_HANDLERS.get(tool_name)
        if handler is None:
            return f"error: unknown tool '{tool_name}'"
        try:
            return handler(**args)
        except TypeError as exc:
            return f"error: invalid arguments for '{tool_name}': {exc}"
        except Exception as exc:  # noqa: BLE001
            return f"error: {exc}"
