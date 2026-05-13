"""Subagent worker for the `task` tool (s_full.py s04).

Spawns a short-lived async ReAct loop with its own restricted toolset
(Explore is read-only; general-purpose can also write/edit) and returns
the final text the model produced. Lives in its own module so
agent_core.py doesn't have to import the tool layer recursively.

Sync handlers run inside `asyncio.to_thread` so the event loop stays
responsive; async handlers (none today) would just be `await`ed.
"""
from __future__ import annotations

import asyncio
import inspect
from typing import Any

from rich_senpai.core.config import (
    MICROCOMPACT_KEEP_RECENT,
    MICROCOMPACT_MIN_KEEP_RECENT,
    SUBAGENT_MAX_ITERATIONS,
    SUBAGENT_MAX_TOKENS_PER_CALL,
    TOOL_COMPACT_AFTER_ROUND,
)
from rich_senpai.core.llm import (
    LLMClient,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from rich_senpai.core.unit.agent.compaction import microcompact
from rich_senpai.tools.file_access import (
    edit_file as edit_file_tool,
    read_file as read_file_tool,
    write_file as write_file_tool,
)
from rich_senpai.tools.memory.recover_compacted_tool_use_result import (
    SPEC as _RECOVER_SPEC,
)
from rich_senpai.tools.shell import bash as bash_tool
from rich_senpai.tools.tool_result import as_text
from rich_senpai.tools.web import web_fetch as web_fetch_tool, web_search as web_search_tool


# Tool sets the subagent exposes to the LLM. The recover tool ships with both
# personas — it's intercepted below, not dispatched through `_HANDLERS`.
# Web tools (search + fetch) are read-only so they ride with Explore as well
# as General.
_WEB_MODULES = (web_search_tool, web_fetch_tool)
_EXPLORE_MODULES = (bash_tool, read_file_tool, *_WEB_MODULES)
_GENERAL_MODULES = (bash_tool, read_file_tool, write_file_tool, edit_file_tool, *_WEB_MODULES)

_EXPLORE_TOOLS = [m.SPEC for m in _EXPLORE_MODULES] + [_RECOVER_SPEC]
_GENERAL_TOOLS = [m.SPEC for m in _GENERAL_MODULES] + [_RECOVER_SPEC]

_HANDLERS = {
    m.SPEC["name"]: getattr(m, m.__name__.rsplit(".", 1)[-1])
    for m in _GENERAL_MODULES
}


async def run_subagent(
    prompt: str,
    *,
    llm: LLMClient,
    agent_type: str = "Explore",
    system: str = "You are a focused subagent. Do exactly what the parent asked, then return a concise summary.",
    max_iterations: int = SUBAGENT_MAX_ITERATIONS,
    max_tokens: int = SUBAGENT_MAX_TOKENS_PER_CALL,
    keep_recent: int = MICROCOMPACT_KEEP_RECENT,
) -> str:
    if keep_recent < MICROCOMPACT_MIN_KEEP_RECENT:
        raise ValueError(
            f"keep_recent must be >= {MICROCOMPACT_MIN_KEEP_RECENT} "
            f"so all progressive compaction tiers are exercised "
            f"(got {keep_recent})"
        )
    tools = _EXPLORE_TOOLS if agent_type == "Explore" else _GENERAL_TOOLS
    messages: list[Message] = [
        Message(role="user", content=[TextBlock(text=prompt)])
    ]
    # Per-subagent recovery map for `recover_compacted_tool_use_result`.
    # Lives for the duration of this loop and is dropped when the function
    # returns. Disjoint from the lead's / sibling subagents' maps.
    recovery_map: dict[str, str] = {}
    last_text = ""

    for i in range(max_iterations):
        # Same cadence as the lead — fire microcompact every `keep_recent`
        # iterations so very-long subagent runs don't bloat their context.
        # if (i+1) % TOOL_COMPACT_AFTER_ROUND == 0:
        #     microcompact(
        #         messages,
        #         recovery_map=recovery_map,
        #         keep_recent=keep_recent,
        #     )

        response = await llm.create_message(
            messages=messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
        )
        messages.append(Message(role="assistant", content=list(response.content)))
        text = "\n".join(b.text for b in response.content if isinstance(b, TextBlock)).strip()
        if text:
            last_text = text
        if response.stop_reason != "tool_use":
            break

        results: list[ToolResultBlock] = []
        for block in response.content:
            if not isinstance(block, ToolUseBlock):
                continue
            if block.name == "recover_compacted_tool_use_result":
                output = _recover_from_map(recovery_map, dict(block.input or {}))
            else:
                handler = _HANDLERS.get(block.name)
                if handler is None:
                    output = f"error: unknown subagent tool '{block.name}'"
                else:
                    kwargs: dict[str, Any] = dict(block.input or {})
                    try:
                        if inspect.iscoroutinefunction(handler):
                            raw = await handler(**kwargs)
                        else:
                            raw = await asyncio.to_thread(handler, **kwargs)
                        output = as_text(raw)
                    except TypeError as exc:
                        output = f"error: invalid arguments for '{block.name}': {exc}"
                    except Exception as exc:  # noqa: BLE001
                        output = f"error: {exc}"
            results.append(ToolResultBlock(tool_use_id=block.id, content=output[:50_000]))
        messages.append(Message(role="user", content=list(results)))

    return last_text or "(no summary)"


def _recover_from_map(recovery_map: dict[str, str], tool_input: dict[str, Any]) -> str:
    """Look up the requested tool_use_id in this subagent's recovery map.

    Returns the original content (as a string suitable for stuffing into a
    ToolResultBlock) or a clear error string when the id is missing —
    same contract as ``AgentCore._handle_recover``.
    """
    tool_use_id = tool_input.get("tool_use_id")
    if not isinstance(tool_use_id, str) or not tool_use_id:
        return "error: 'tool_use_id' is required and must be a non-empty string."
    original = recovery_map.get(tool_use_id)
    if original is None:
        return (
            f"error: no original content for tool_use_id={tool_use_id!r}. "
            "It was never compacted, the id is wrong, or it has been evicted."
        )
    return original
