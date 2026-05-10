"""Persistent autonomous teammates (s_full.py s09 + s11).

A teammate is an `asyncio.Task` running its own ReAct loop on the main
event loop. It talks to the lead through MessageBus, claims work off
the file-backed TaskManager when idle, and obeys shutdown_request
messages. Each teammate's identity is re-injected if the message list
ever shrinks (e.g. after compaction) so it doesn't forget who it is.

Sync filesystem/shell tool handlers are dispatched through
`asyncio.to_thread` so the loop stays responsive while subprocesses
run.
"""
from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
from typing import Any

from core import config
from core.compaction import auto_compact, estimate_tokens, microcompact
from core.config import (
    TEAM_IDLE_TIMEOUT,
    TEAM_MAX_TOKENS,
    TEAM_POLL_INTERVAL,
    TEAM_TOKEN_THRESHOLD,
)
from core.llm import (
    LLMClient,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from core.logging_setup import clip, get_logger
from core.messaging import MessageBus
from core.tasks_file import TaskManager
from tools import (
    bash as bash_tool,
    claim_task as claim_task_tool,
    edit_file as edit_file_tool,
    idle as idle_tool,
    read_file as read_file_tool,
    send_message as send_message_tool,
    write_file as write_file_tool,
)
from tools.tool_result import as_text


log = get_logger(__name__)


# Filesystem / shell tools the teammate can call directly through
# `_FS_HANDLERS`. Messaging and task-board tools are dispatched manually
# in `_dispatch` so they can be scoped to the teammate's identity rather
# than the lead.
_FS_TOOL_MODULES = (bash_tool, read_file_tool, write_file_tool, edit_file_tool)

_FS_HANDLERS = {
    m.SPEC["name"]: getattr(m, m.__name__.rsplit(".", 1)[-1])
    for m in _FS_TOOL_MODULES
}

_TEAMMATE_TOOLS = [
    *(m.SPEC for m in _FS_TOOL_MODULES),
    send_message_tool.SPEC,
    idle_tool.SPEC,
    claim_task_tool.SPEC,
]


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
        # Loop tasks per teammate name. Populated by `spawn`; cancelled on
        # app shutdown via Textual's task lifecycle.
        self.tasks: dict[str, asyncio.Task[None]] = {}

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
        if member is None:
            return
        old = member.get("status")
        if old == status:
            return
        member["status"] = status
        self._save_config()
        log.info("teammate=%s status %s -> %s", name, old, status)

    def member_names(self) -> list[str]:
        return [m["name"] for m in self.config["members"]]

    def member_snapshot(self) -> list[dict[str, Any]]:
        """Shallow copy of the persisted member list for read-only views
        (TUI panel, /team command). Each dict has {name, role, status}."""
        return [
            {"name": m["name"], "role": m["role"], "status": m.get("status", "?")}
            for m in self.config["members"]
        ]

    def list_all(self) -> str:
        if not self.config["members"]:
            return "No teammates."
        lines = [f"Team: {self.config['team_name']}"]
        for m in self.config["members"]:
            lines.append(f"  {m['name']} ({m['role']}): {m['status']}")
        return "\n".join(lines)

    def spawn(self, name: str, role: str, prompt: str) -> str:
        """Start a teammate's ReAct loop as an asyncio.Task on the running
        loop. Must be called from a coroutine context (the spawn_teammate
        tool is async, so this is satisfied by the dispatch path)."""
        member = self._find(name)
        if member:
            if member["status"] not in ("idle", "shutdown"):
                log.info(
                    "spawn rejected name=%s role=%s reason=already %s",
                    name,
                    role,
                    member["status"],
                )
                return f"error: '{name}' is currently {member['status']}"
            member["status"] = "working"
            member["role"] = role
        else:
            member = {"name": name, "role": role, "status": "working"}
            self.config["members"].append(member)
        self._save_config()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            log.warning("spawn name=%s no running loop", name)
            return (
                f"error: cannot spawn '{name}' outside a running event loop "
                f"(spawn_teammate must be called via the async tool dispatch path)"
            )
        task = loop.create_task(self._loop(name, role, prompt))
        self.tasks[name] = task
        log.info("spawn name=%s role=%s prompt=%s", name, role, clip(prompt))
        return f"Spawned '{name}' (role: {role})"

    async def _loop(self, name: str, role: str, prompt: str) -> None:
        team_name = self.config["team_name"]
        workdir = config.WORKDIR
        sys_prompt = (
            f"You are '{name}', role: {role}, team: {team_name}, at {workdir}. "
            f"Use idle when done with current work. You may auto-claim tasks."
        )
        messages: list[Message] = [
            Message(role="user", content=[TextBlock(text=prompt)])
        ]
        log.info("teammate=%s loop start role=%s team=%s", name, role, team_name)

        try:
            while True:
                # ---- WORK PHASE ---------------------------------------------
                log.debug("teammate=%s entering work phase", name)
                for work_iter in range(50):
                    # Compaction first — keeps the teammate's context from
                    # growing unbounded across long-running auto-claim
                    # cycles. microcompact collapses old tool_results
                    # cheaply; auto_compact runs an LLM-backed summary
                    # only if the budget is genuinely blown.
                    microcompact(messages, keep_recent=3)
                    await self._maybe_compact(name, messages, sys_prompt)

                    inbox = self.bus.read_inbox(name)
                    if inbox:
                        log.info(
                            "teammate=%s inbox_drain count=%d",
                            name,
                            len(inbox),
                        )
                    shutdown_msg: dict[str, Any] | None = None
                    for msg in inbox:
                        if msg.get("type") == "shutdown_request":
                            shutdown_msg = msg
                            break
                        messages.append(
                            Message(role="user", content=[TextBlock(text=json.dumps(msg))])
                        )
                    if shutdown_msg is not None:
                        log.info("teammate=%s shutdown_request received", name)
                        self._send_shutdown_response(
                            name, shutdown_msg.get("request_id")
                        )
                        self._set_status(name, "shutdown")
                        return

                    log.info(
                        "teammate=%s work_iter=%d llm_request messages=%d",
                        name,
                        work_iter,
                        len(messages),
                    )
                    try:
                        response = await self.llm.create_message(
                            messages=messages,
                            system=sys_prompt,
                            tools=_TEAMMATE_TOOLS,
                            max_tokens=TEAM_MAX_TOKENS,
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        # Don't swallow — capture the traceback in the log
                        # and surface a one-line error to the lead so the
                        # smoke-test driver can see why the teammate died.
                        log.exception(
                            "teammate=%s LLM call failed; shutting down",
                            name,
                        )
                        self._notify_lead_of_crash(name, exc)
                        self._set_status(name, "shutdown")
                        return

                    log.info(
                        "teammate=%s work_iter=%d llm_response stop=%s in=%d out=%d",
                        name,
                        work_iter,
                        response.stop_reason,
                        response.usage.input_tokens,
                        response.usage.output_tokens,
                    )
                    messages.append(Message(role="assistant", content=list(response.content)))
                    if response.stop_reason != "tool_use":
                        break

                    results: list[ToolResultBlock] = []
                    idle_requested = False
                    for block in response.content:
                        if not isinstance(block, ToolUseBlock):
                            continue
                        tool_input = dict(block.input or {})
                        log.info(
                            "teammate=%s tool_use name=%s id=%s",
                            name,
                            block.name,
                            block.id,
                        )
                        log.debug(
                            "teammate=%s tool_use name=%s input=%s",
                            name,
                            block.name,
                            clip(tool_input),
                        )
                        output = await self._dispatch(name, block.name, tool_input)
                        if block.name == "idle":
                            idle_requested = True
                        log.info(
                            "teammate=%s tool_result name=%s output_chars=%d",
                            name,
                            block.name,
                            len(str(output)),
                        )
                        log.debug(
                            "teammate=%s tool_result name=%s output=%s",
                            name,
                            block.name,
                            clip(output),
                        )
                        results.append(ToolResultBlock(tool_use_id=block.id, content=str(output)))
                    messages.append(Message(role="user", content=list(results)))
                    if idle_requested:
                        break

                # ---- IDLE PHASE ---------------------------------------------
                self._set_status(name, "idle")
                log.debug("teammate=%s entering idle phase", name)
                resume = False
                for _ in range(max(TEAM_IDLE_TIMEOUT // TEAM_POLL_INTERVAL, 1)):
                    await asyncio.sleep(TEAM_POLL_INTERVAL)
                    inbox = self.bus.read_inbox(name)
                    if inbox:
                        log.info(
                            "teammate=%s idle inbox_drain count=%d",
                            name,
                            len(inbox),
                        )
                        for msg in inbox:
                            if msg.get("type") == "shutdown_request":
                                log.info(
                                    "teammate=%s shutdown_request received during idle",
                                    name,
                                )
                                self._send_shutdown_response(
                                    name, msg.get("request_id")
                                )
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
                        log.info(
                            "teammate=%s auto_claimed task_id=%s subject=%s",
                            name,
                            task["id"],
                            clip(task.get("subject", "")),
                        )
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
                    log.info(
                        "teammate=%s idle timeout reached, shutting down",
                        name,
                    )
                    self._set_status(name, "shutdown")
                    return
                self._set_status(name, "working")
        except asyncio.CancelledError:
            # App shutdown or explicit task cancel — leave a clean status.
            log.info("teammate=%s loop cancelled", name)
            self._set_status(name, "shutdown")
            raise
        except Exception as exc:
            # Catch-all so the crash is visible in the log and the lead
            # gets a notification rather than the asyncio task vanishing
            # with an "exception was never retrieved" warning at exit.
            log.exception("teammate=%s loop crashed", name)
            self._notify_lead_of_crash(name, exc)
            self._set_status(name, "shutdown")

    def _notify_lead_of_crash(self, name: str, exc: BaseException) -> None:
        """Send a one-line error message to the lead's inbox so the lead
        agent can surface a teammate's silent death to the user. Best
        effort — failures here are logged but never re-raised."""
        try:
            self.bus.send(
                name,
                "lead",
                f"teammate '{name}' crashed: {type(exc).__name__}: {exc}",
                msg_type="message",
            )
        except Exception:
            log.exception("teammate=%s failed to notify lead of crash", name)

    def _send_shutdown_response(
        self,
        name: str,
        request_id: str | None,
        detail: str = "shutdown complete",
    ) -> None:
        """Confirm via the bus that a teammate is shutting down in
        response to a `shutdown_request`. Carries the original
        `request_id` so the lead's inbox-drain pipeline can pop the
        outstanding entry from `core.messaging.shutdown_requests` and
        the lead's agent sees a positive ack rather than just a status
        change in the panel. Best effort — failures are logged but
        never re-raised, since the teammate is already on its way out."""
        extra = {"request_id": request_id} if request_id else None
        try:
            self.bus.send(
                name,
                "lead",
                f"teammate '{name}' {detail}",
                msg_type="shutdown_response",
                extra=extra,
            )
            log.info(
                "teammate=%s shutdown_response sent request_id=%s",
                name,
                request_id,
            )
        except Exception:
            log.exception(
                "teammate=%s failed to send shutdown_response request_id=%s",
                name,
                request_id,
            )

    async def _maybe_compact(
        self,
        name: str,
        messages: list[Message],
        sys_prompt: str,
    ) -> None:
        """Auto-compact a teammate's message list when its estimated
        token count crosses ``TEAM_TOKEN_THRESHOLD``. Called at the top
        of every work-phase iteration. Replaces ``messages`` in place
        with the compressed form so the loop's identity-injection guard
        (``len(messages) <= 3``) trips correctly on the next claim."""
        tokens = estimate_tokens(messages)
        if tokens <= TEAM_TOKEN_THRESHOLD:
            return
        log.info(
            "teammate=%s auto_compact triggered tokens=%d threshold=%d messages=%d",
            name,
            tokens,
            TEAM_TOKEN_THRESHOLD,
            len(messages),
        )
        messages[:] = await auto_compact(
            messages,
            llm=self.llm,
            system=sys_prompt,
        )
        log.info(
            "teammate=%s auto_compact done messages=%d",
            name,
            len(messages),
        )

    async def _dispatch(self, name: str, tool_name: str, args: dict[str, Any]) -> str:
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
            log.warning("teammate=%s unknown tool=%s", name, tool_name)
            return f"error: unknown tool '{tool_name}'"
        try:
            if inspect.iscoroutinefunction(handler):
                raw = await handler(**args)
            else:
                raw = await asyncio.to_thread(handler, **args)
            return as_text(raw)
        except TypeError as exc:
            log.warning(
                "teammate=%s invalid args tool=%s err=%s",
                name,
                tool_name,
                exc,
            )
            return f"error: invalid arguments for '{tool_name}': {exc}"
        except Exception as exc:
            log.exception(
                "teammate=%s tool=%s raised; recovering",
                name,
                tool_name,
            )
            return f"error: {exc}"
