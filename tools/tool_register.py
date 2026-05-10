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
from types import ModuleType
from typing import Any, Awaitable, Callable, Union

from tools.tool_result import ToolResult, as_text  # re-exported below

from tools import (
    background_run,
    bash,
    broadcast,
    check_background,
    claim_task,
    compress,
    edit_file,
    http_request,
    idle,
    list_teammates,
    load_skill,
    plan_approval,
    read_file,
    read_inbox,
    send_message,
    shutdown_request,
    spawn_teammate,
    task,
    task_create,
    task_get,
    task_list,
    task_update,
    todo_write,
    update_short_memory,
    wait,
    write_file,
)


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
        http_request,
        update_short_memory,
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
        return ToolResult(text=f"error: unknown tool '{name}'", ok=False)
    args = arguments or {}
    try:
        if inspect.iscoroutinefunction(handler):
            raw = await handler(**args)
        else:
            raw = await asyncio.to_thread(handler, **args)
    except TypeError as exc:
        return ToolResult(text=f"error: invalid arguments for '{name}': {exc}", ok=False)
    if isinstance(raw, ToolResult):
        return raw
    return ToolResult(text=str(raw), ok=True)
