"""Subagent worker for the `task` tool (s_full.py s04).

Spawns a short-lived ReAct loop with its own restricted toolset (Explore
is read-only; general-purpose can also write/edit) and returns the final
text the model produced. Lives in its own module so agent_core.py
doesn't have to import the tool layer recursively.
"""
from __future__ import annotations

from typing import Any

from core.config import SUBAGENT_MAX_ITERATIONS, SUBAGENT_MAX_TOKENS
from core.llm import (
    LLMClient,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from tools import bash as bash_tool
from tools import edit_file as edit_file_tool
from tools import read_file as read_file_tool
from tools import write_file as write_file_tool


_EXPLORE_TOOLS = [bash_tool.SPEC, read_file_tool.SPEC]
_GENERAL_TOOLS = [
    bash_tool.SPEC,
    read_file_tool.SPEC,
    write_file_tool.SPEC,
    edit_file_tool.SPEC,
]

_HANDLERS = {
    bash_tool.SPEC["name"]: bash_tool.bash,
    read_file_tool.SPEC["name"]: read_file_tool.read_file,
    write_file_tool.SPEC["name"]: write_file_tool.write_file,
    edit_file_tool.SPEC["name"]: edit_file_tool.edit_file,
}


def run_subagent(
    prompt: str,
    *,
    llm: LLMClient,
    agent_type: str = "Explore",
    system: str = "You are a focused subagent. Do exactly what the parent asked, then return a concise summary.",
    max_iterations: int = SUBAGENT_MAX_ITERATIONS,
    max_tokens: int = SUBAGENT_MAX_TOKENS,
) -> str:
    tools = _EXPLORE_TOOLS if agent_type == "Explore" else _GENERAL_TOOLS
    messages: list[Message] = [
        Message(role="user", content=[TextBlock(text=prompt)])
    ]
    last_text = ""

    for _ in range(max_iterations):
        response = llm.create_message(
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
            handler = _HANDLERS.get(block.name)
            if handler is None:
                output = f"error: unknown subagent tool '{block.name}'"
            else:
                kwargs: dict[str, Any] = dict(block.input or {})
                try:
                    output = handler(**kwargs)
                except TypeError as exc:
                    output = f"error: invalid arguments for '{block.name}': {exc}"
                except Exception as exc:  # noqa: BLE001
                    output = f"error: {exc}"
            results.append(ToolResultBlock(tool_use_id=block.id, content=str(output)[:50_000]))
        messages.append(Message(role="user", content=list(results)))

    return last_text or "(no summary)"
