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

from rich_senpai.core import config
from rich_senpai.core.llm import LLMClient, Message, TextBlock, ToolResultBlock


TRANSCRIPT_DIR = config.TRANSCRIPT_DIR


# Progressive compaction tiers — applied newest-first to user-turn messages
# beyond the `keep_recent` window. Position keep_recent+1 takes index 0 (50%),
# keep_recent+2 takes index 1 (30%), … keep_recent+6 takes index 5 (1%).
# Anything older clamps at the deepest tier.
_COMPACTION_TIERS: tuple[float, ...] = (0.50, 0.30, 0.20, 0.10, 0.05, 0.01)


def microcompact(
    messages: list[Message],
    *,
    recovery_map: dict[str, str],
    keep_recent: int | None = None,
    min_len: int | None = None,
    recovery_cap: int | None = None,
) -> None:
    """Progressive in-place compaction.

    Walk user-turn messages containing ``ToolResultBlock``s from newest to
    oldest. Leave the first ``keep_recent`` of them untouched. For every
    block older than that, compact its content to the first N% of the
    *original* (looked up from ``recovery_map``; stored on first touch).
    Tier ladder: position keep_recent+1 → 50%, +2 → 30%, +3 → 20%,
    +4 → 10%, +5 → 5%, +6 → 1%; older positions clamp at 1%.

    Always operating on the original — never re-truncating an already-
    stubbed body — keeps the byte content at a given position deterministic
    so a block can pass through tiers cleanly as it sinks, and a re-run
    produces identical bytes (prompt-cache friendly).

    ``recovery_map`` is mutated in place: tool_use_id → original content.
    A soft FIFO cap drops the oldest entry when ``recovery_cap`` is hit.
    Blocks shorter than ``min_len`` are skipped entirely (the stub would
    be longer than the original).
    """
    if keep_recent is None:
        keep_recent = config.MICROCOMPACT_KEEP_RECENT
    if min_len is None:
        min_len = config.MICROCOMPACT_MIN_LEN
    if recovery_cap is None:
        recovery_cap = config.MICROCOMPACT_RECOVERY_CAP

    indices = [
        i for i, m in enumerate(messages)
        # only compact user turns carrying tool_results, not raw user input.
        if m.role == "user"
        and any(isinstance(b, ToolResultBlock) for b in m.content)
    ]
    if len(indices) <= keep_recent:
        return

    # Walk newest → oldest so position 1 = freshest tool_result user-turn.
    for pos1, idx in enumerate(reversed(indices), start=1):
        if pos1 <= keep_recent:
            continue
        tier = _COMPACTION_TIERS[min(pos1 - keep_recent - 1, len(_COMPACTION_TIERS) - 1)]
        new_content: list[Any] = []
        for block in messages[idx].content:
            if not isinstance(block, ToolResultBlock):
                new_content.append(block)
                continue
            original = _resolve_original(block, recovery_map, recovery_cap)
            if len(original) <= min_len:
                # Tiny output — stub would be larger than the body.
                new_content.append(block)
                continue
            new_content.append(
                ToolResultBlock(
                    tool_use_id=block.tool_use_id,
                    content=_make_stub(original, block.tool_use_id, tier),
                )
            )
        messages[idx].content = new_content


def _resolve_original(
    block: ToolResultBlock,
    recovery_map: dict[str, str],
    recovery_cap: int,
) -> str:
    """Return the original content for ``block`` — looked up by id if we
    already stashed it, otherwise stashed now. The cap is enforced via
    FIFO insertion order on the dict (Python 3.7+ preserves it)."""
    existing = recovery_map.get(block.tool_use_id)
    if existing is not None:
        return existing
    recovery_map[block.tool_use_id] = block.content
    while len(recovery_map) > recovery_cap:
        # popitem(last=False) on an OrderedDict, but plain dict is FIFO too —
        # grab the first key by iteration and pop it.
        oldest = next(iter(recovery_map))
        recovery_map.pop(oldest, None)
    return block.content


def _make_stub(original: str, tool_use_id: str, ratio: float) -> str:
    prefix_len = max(1, int(len(original) * ratio))
    prefix = original[:prefix_len]
    pct = int(round(ratio * 100))
    return (
        f"{prefix}\n[... compacted {pct}%, {len(original)} chars total, "
        f"{prefix_len} shown — call recover_compacted_tool_use_result"
        f'(tool_use_id="{tool_use_id}") to restore the full output]'
    )


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
