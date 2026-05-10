"""Conversation compaction.

Two strategies stacked on top of each other:

* `microcompact`: in-place rewrite of older tool_result blocks to a short
  stub. Cheap, idempotent, runs every turn.
* `auto_compact`: full transcript replacement via an LLM-written summary.
  Expensive, runs when the conversation crosses a token threshold.

Microcompact lives here too (was inline in agent_core); keeping both in
one module so the budgeting logic is in one place.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from core import config
from core.llm import LLMClient, Message, TextBlock, ToolResultBlock


TRANSCRIPT_DIR = config.TRANSCRIPT_DIR


def microcompact(
    messages: list[Message],
    *,
    keep_recent: int = 2,
    threshold: int = 200,
) -> None:
    """In place: replace tool_result content in older user turns with a
    compact stub, preserving tool_use_id so the model can still match
    results to calls."""
    indices = [
        i for i, m in enumerate(messages)
        if m.role == "user"
        and any(isinstance(b, ToolResultBlock) for b in m.content)
    ]
    if len(indices) <= keep_recent:
        return

    to_compact = indices[:-keep_recent] if keep_recent > 0 else indices
    for idx in to_compact:
        new_content: list[Any] = []
        for block in messages[idx].content:
            if isinstance(block, ToolResultBlock) and len(block.content) > threshold:
                stub = f"[compacted: {len(block.content)} chars elided]"
                new_content.append(
                    ToolResultBlock(tool_use_id=block.tool_use_id, content=stub)
                )
            else:
                new_content.append(block)
        messages[idx].content = new_content


def estimate_tokens(messages: list[Message]) -> int:
    """Cheap heuristic — 4 chars per token over the JSON-serialized form."""
    serial = json.dumps(_serialize(messages), default=str)
    return len(serial) // 4


async def auto_compact(
    messages: list[Message],
    *,
    llm: LLMClient,
    system: str,
    transcript_dir: Path = TRANSCRIPT_DIR,
) -> list[Message]:
    """Snapshot the transcript to disk, ask the LLM to summarize for
    continuity, then return a brand-new message list seeded with that
    summary. Caller replaces its messages with the return value."""
    transcript_dir.mkdir(parents=True, exist_ok=True)
    path = transcript_dir / f"transcript_{int(time.time())}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for m in messages:
            f.write(json.dumps({"role": m.role, "content": _serialize_blocks(m.content)}, default=str) + "\n")

    conv_text = json.dumps(_serialize(messages), default=str)[-80_000:]
    summary_resp = await llm.create_message(
        messages=[Message(role="user", content=[TextBlock(text=f"Summarize for continuity:\n{conv_text}")])],
        system=system,
        tools=[],
        max_tokens=2000,
    )
    summary = "\n".join(b.text for b in summary_resp.content if isinstance(b, TextBlock)).strip()
    if not summary:
        summary = "(no summary returned)"

    return [
        Message(
            role="user",
            content=[TextBlock(text=f"[Compressed. Transcript: {path}]\n{summary}")],
        ),
    ]


def _serialize(messages: list[Message]) -> list[dict[str, Any]]:
    return [{"role": m.role, "content": _serialize_blocks(m.content)} for m in messages]


def _serialize_blocks(blocks: list[Any]) -> list[Any]:
    out: list[Any] = []
    for b in blocks:
        if is_dataclass(b):
            out.append(asdict(b))
        elif isinstance(b, dict):
            out.append(b)
        else:
            out.append(repr(b))
    return out
