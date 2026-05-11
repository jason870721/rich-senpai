"""Single source of truth for the lead agent's tool surface.

Every tool module exposes:

* ``SPEC``    — an Anthropic-shaped tool spec ``{name, description, input_schema}``
* a top-level callable (sync **or** async) whose attribute name matches
  the module name (e.g. ``tools.read_file`` exports ``read_file``)

Adding a tool is therefore a two-step change: create the module, then drop
its reference into the appropriate group below. ``TOOL_SPECS`` and
``TOOL_HANDLERS`` are derived automatically from the grouped list — no
parallel imports / dicts to keep in sync.

The grouping is purely organisational; downstream code sees a single flat
``TOOL_SPECS`` list, ordered group-by-group.

``call_tool`` is async: sync handlers run on a worker thread via
``asyncio.to_thread`` so the event loop stays responsive; async handlers
are awaited directly. Tools that need to schedule asyncio work (e.g.
``task``, ``spawn_teammate``) MUST be defined ``async def`` so they
execute on the loop.
"""
from __future__ import annotations

import asyncio
import inspect
import time
from types import ModuleType
from typing import Any, Awaitable, Callable, Union

from rich_senpai.core.logging_setup import clip, get_logger
from rich_senpai.tools.tool_result import ToolResult, as_text  # re-exported below


log = get_logger(__name__)

from rich_senpai.tools.delegation import list_teammates, spawn_teammate, task
from rich_senpai.tools.file_access import edit_file, read_file, write_file
from rich_senpai.tools.memory import (
    compress,
    idle,
    load_skill,
    recover_compacted_tool_use_result,
    todo_write,
    update_master_profile,
    wait,
)
from rich_senpai.tools.messaging import (
    broadcast,
    plan_approval,
    read_inbox,
    send_message,
    shutdown_request,
)
from rich_senpai.tools.shell import background_run, bash, check_background
from rich_senpai.tools.task_board import (
    claim_task,
    task_create,
    task_get,
    task_list,
    task_update,
)
from rich_senpai.tools.web import web_fetch, web_search


# ---------------------------------------------------------------------------
# Tool catalogue. Order inside each group is preserved in TOOL_SPECS so the
# model sees related tools next to each other.
# ---------------------------------------------------------------------------
TOOL_GROUPS: dict[str, list[ModuleType]] = {
    "fs_shell_data": [
        read_file,
        write_file,
        edit_file,
        bash,
        background_run,
        check_background,
    ],
    "working_memory": [
        todo_write,
        task_create,
        task_get,
        task_update,
        task_list,
        claim_task,
    ],
    "delegation": [
        task,
        spawn_teammate,
        list_teammates,
        send_message,
        read_inbox,
        broadcast,
        shutdown_request,
        plan_approval,
    ],
    "context_management": [
        load_skill,
        compress,
        idle,
        wait,
        update_master_profile,
        recover_compacted_tool_use_result,
    ],
    "web_explore": [
        web_search,
        web_fetch,
    ],
}


# `ToolResult` and `as_text` live in `tools.tool_result` to avoid a
# circular import (this module imports every tool at load time, and
# tool modules now reference `ToolResult`). They're re-exported here
# for callers that already import from `tool_register`.
__all__ = ["ToolResult", "as_text", "TOOL_SPECS", "TOOL_HANDLERS", "call_tool"]

_ToolReturn = Union[str, ToolResult]
_ToolHandler = Union[
    Callable[..., _ToolReturn],
    Callable[..., Awaitable[_ToolReturn]],
]


def _handler_for(module: ModuleType) -> _ToolHandler:
    """Resolve a tool module's callable handler.

    Convention: the handler attribute name equals the module's last path
    segment (``tools.read_file`` -> ``read_file``). May be a regular
    function or a coroutine function.
    """
    func_name = module.__name__.rsplit(".", 1)[-1]
    handler = getattr(module, func_name, None)
    if not callable(handler):
        raise RuntimeError(
            f"tool module '{module.__name__}' is missing a callable "
            f"named '{func_name}'"
        )
    return handler


_ALL_MODULES: list[ModuleType] = [
    module for group in TOOL_GROUPS.values() for module in group
]

TOOL_SPECS: list[dict[str, Any]] = [m.SPEC for m in _ALL_MODULES]

TOOL_HANDLERS: dict[str, _ToolHandler] = {
    m.SPEC["name"]: _handler_for(m) for m in _ALL_MODULES
}


async def call_tool(name: str, arguments: dict[str, Any] | None = None) -> ToolResult:
    """Dispatch a tool_use block by name.

    Async handlers are awaited directly; sync handlers run on a worker
    thread via ``asyncio.to_thread`` so the event loop stays responsive.
    Returns a `ToolResult` — handlers that returned a plain string are
    normalized to `ToolResult(text=..., ok=True)`; unknown-tool / bad-args
    failures come back with `ok=False`.
    """
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        log.warning("call_tool unknown tool name=%s", name)
        return ToolResult(text=f"error: unknown tool '{name}'", ok=False)
    args = arguments or {}
    log.debug("call_tool start name=%s input=%s", name, clip(args))
    started = time.monotonic()
    try:
        if inspect.iscoroutinefunction(handler):
            raw = await handler(**args)
        else:
            raw = await asyncio.to_thread(handler, **args)
    except TypeError as exc:
        log.warning("call_tool invalid args name=%s err=%s", name, exc)
        return ToolResult(text=f"error: invalid arguments for '{name}': {exc}", ok=False)
    elapsed_ms = (time.monotonic() - started) * 1000
    if isinstance(raw, ToolResult):
        result = raw
    else:
        result = ToolResult(text=str(raw), ok=True)
    log.debug(
        "call_tool done name=%s ok=%s elapsed_ms=%.1f output=%s",
        name,
        result.ok,
        elapsed_ms,
        clip(result.text),
    )
    return result
