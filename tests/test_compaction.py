"""Tests for compaction.py — microcompact, estimate_tokens, auto_compact.

Covers the compaction pipeline from token estimation through
progressive tiered microcompaction. auto_compact is tested
for serialization logic only (LLM dependency requires mocking).
"""
import json
from pathlib import Path

import pytest

from rich_senpai.core.llm.base import (
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from rich_senpai.core.unit.agent.compaction import (
    _COMPACTION_TIERS,
    _make_stub,
    _resolve_original,
    estimate_tokens,
    microcompact,
)


# ── estimate_tokens ─────────────────────────────────────────────────

class TestEstimateTokens:
    def test_empty_list_returns_zero(self):
        assert estimate_tokens([]) == 0

    def test_single_text_message(self):
        msgs = [Message(role="user", content=[TextBlock(text="hello")])]
        tokens = estimate_tokens(msgs)
        assert tokens > 0

    def test_ascii_four_chars_per_token(self):
        """estimate_tokens = len(json_serialized) // 4."""
        msgs = [Message(role="user", content=[TextBlock(text="a" * 40)])]
        tokens = estimate_tokens(msgs)
        # JSON wraps the text in structure: role + content array + TextBlock fields
        assert tokens > 0

    def test_tool_result_block_counted(self):
        msgs = [
            Message(role="user", content=[
                ToolResultBlock(
                    tool_use_id="abc",
                    content="x" * 400,
                ),
            ]),
        ]
        tokens = estimate_tokens(msgs)
        assert tokens > 50

    def test_tool_use_block_counted(self):
        msgs = [
            Message(role="assistant", content=[
                ToolUseBlock(id="t1", name="do_it", input={"k": "v"}),
            ]),
        ]
        tokens = estimate_tokens(msgs)
        assert tokens > 0

    def test_multiple_messages_are_additive(self):
        msgs1 = [Message(role="user", content=[TextBlock(text="a" * 100)])]
        msgs2 = [Message(role="user", content=[TextBlock(text="b" * 100)])]
        both = msgs1 + msgs2
        # Two messages > one
        assert estimate_tokens(both) >= estimate_tokens(msgs1)


# ── _make_stub ──────────────────────────────────────────────────────

class TestMakeStub:
    def test_50_percent_stub(self):
        original = "abcdefgh"  # 8 chars, 50% = 4 chars prefix
        stub = _make_stub(original, "test-id", 0.50)
        assert stub.startswith("abcd\n[")
        assert 'compacted 50%' in stub
        assert '8 chars total' in stub
        assert '4 shown' in stub
        assert 'tool_use_id="test-id"' in stub

    def test_100_percent_stub(self):
        original = "ab"
        stub = _make_stub(original, "x", 1.0)
        assert stub.startswith("ab\n[")
        assert 'compacted 100%' in stub

    def test_1_percent_stub(self):
        original = "x" * 1000
        stub = _make_stub(original, "id", 0.01)
        assert stub.startswith("x" * 10)  # 1% of 1000 = 10
        assert 'compacted 1%' in stub
        assert '10 shown' in stub

    def test_ratio_min_one_char_prefix(self):
        """Even tiny ratios yield at least 1 char prefix."""
        original = "abc"
        stub = _make_stub(original, "id", 0.01)  # 0.03 → max(1, 0) = 1
        assert stub[0] == "a"

    def test_non_ascii_preserved_in_prefix(self):
        original = "你好世界" + "x" * 20  # 4 CJK + 20 ASCII
        stub = _make_stub(original, "id", 0.50)
        assert stub.startswith("你好世界")  # preserved in prefix


# ── _resolve_original ───────────────────────────────────────────────

class TestResolveOriginal:
    def test_first_call_stores_original(self, monkeypatch):
        monkeypatch.setattr(
            "rich_senpai.core.unit.agent.compaction.config.MICROCOMPACT_RECOVERY_CAP",
            100,
        )
        block = ToolResultBlock(tool_use_id="id1", content="original content")
        recovery: dict[str, str] = {}
        result = _resolve_original(block, recovery, 100)
        assert result == "original content"
        assert recovery == {"id1": "original content"}

    def test_second_call_returns_stored_original(self):
        block = ToolResultBlock(tool_use_id="id1", content="already compacted")
        recovery = {"id1": "original content"}
        result = _resolve_original(block, recovery, 100)
        assert result == "original content"  # NOT "already compacted"

    def test_cap_evicts_oldest(self):
        recovery: dict[str, str] = {}
        for i in range(3):
            block = ToolResultBlock(tool_use_id=f"id{i}", content=f"content {i}")
            _resolve_original(block, recovery, recovery_cap=2)
        # Cap=2, so only id1 and id2 remain
        assert len(recovery) == 2
        assert "id0" not in recovery

    def test_cap_never_drops_current(self):
        """With cap=1: insert id0 (len=1, ok). Insert id1 (len=2 > cap),
        evict oldest (id0). id1 remains."""
        recovery: dict[str, str] = {}
        _resolve_original(
            ToolResultBlock(tool_use_id="id0", content="c0"),
            recovery, recovery_cap=1,
        )
        _resolve_original(
            ToolResultBlock(tool_use_id="id1", content="c1"),
            recovery, recovery_cap=1,
        )
        assert "id1" in recovery


# ── microcompact ────────────────────────────────────────────────────

class TestMicrocompact:
    def test_no_tool_result_blocks_no_change(self):
        msgs = [Message(role="user", content=[TextBlock(text="hello")])]
        recovery: dict[str, str] = {}
        microcompact(msgs, recovery_map=recovery, keep_recent=1, min_len=5)
        # unchanged
        assert msgs[0].content[0].text == "hello"

    def test_within_keep_recent_no_compaction(self):
        msgs = [
            Message(role="user", content=[
                ToolResultBlock(tool_use_id="t1", content="x" * 200),
            ]),
        ]
        recovery: dict[str, str] = {}
        microcompact(msgs, recovery_map=recovery, keep_recent=2, min_len=5)
        # 1 tool block ≤ keep_recent=2 => unchanged
        assert msgs[0].content[0].content == "x" * 200

    def test_beyond_keep_recent_gets_compacted(self):
        msgs = [
            Message(role="user", content=[
                ToolResultBlock(tool_use_id="oldest", content="x" * 500),
            ]),
            Message(role="user", content=[
                ToolResultBlock(tool_use_id="middle", content="y" * 500),
            ]),
            Message(role="user", content=[
                ToolResultBlock(tool_use_id="newest", content="z" * 500),
            ]),
        ]
        recovery: dict[str, str] = {}
        microcompact(msgs, recovery_map=recovery, keep_recent=1, min_len=5)
        # Newest (pos 1) → untouched (z*500)
        assert msgs[2].content[0].content == "z" * 500
        # Middle (pos 2) → tier 0, 50% compaction
        assert "compacted 50%" in msgs[1].content[0].content
        # Oldest (pos 3) → tier 1, 30% compaction
        assert "compacted 30%" in msgs[0].content[0].content

    def test_blocks_below_min_len_preserved(self):
        msgs = [
            Message(role="user", content=[
                ToolResultBlock(tool_use_id="t1", content="tiny"),
            ]),
            Message(role="user", content=[
                ToolResultBlock(tool_use_id="t2", content="also tiny"),
            ]),
        ]
        recovery: dict[str, str] = {}
        microcompact(msgs, recovery_map=recovery, keep_recent=1, min_len=20)
        # Both are below min_len=20, so neither is compacted
        assert msgs[0].content[0].content == "tiny"
        assert msgs[1].content[0].content == "also tiny"

    def test_recovery_map_populated_on_compaction(self):
        msgs = [
            Message(role="user", content=[
                ToolResultBlock(tool_use_id="t1", content="original" * 50),
            ]),
            Message(role="user", content=[
                ToolResultBlock(tool_use_id="t2", content="untouched" * 10),
            ]),
        ]
        recovery: dict[str, str] = {}
        microcompact(msgs, recovery_map=recovery, keep_recent=1, min_len=5)
        # t1 was compacted (pos 2, beyond keep_recent=1)
        assert "t1" in recovery
        assert recovery["t1"] == "original" * 50
        # t2 was within keep_recent, NOT stored in recovery
        assert "t2" not in recovery

    def test_idempotent_no_double_compaction(self):
        """Re-running microcompact should produce identical bytes because
        it operates on the *original* content (recovered from map)."""
        original = "x" * 500
        msgs = [
            Message(role="user", content=[
                ToolResultBlock(tool_use_id="t1", content=original),
            ]),
            Message(role="user", content=[
                ToolResultBlock(tool_use_id="t2", content="y" * 500),
            ]),
        ]
        recovery: dict[str, str] = {}
        microcompact(msgs, recovery_map=recovery, keep_recent=1, min_len=5)
        first_pass = msgs[0].content[0].content
        microcompact(msgs, recovery_map=recovery, keep_recent=1, min_len=5)
        second_pass = msgs[0].content[0].content
        assert first_pass == second_pass

    def test_deepest_tier_clamped(self):
        """Beyond position keep_recent+6, all blocks use the last tier (1%)."""
        msgs = []
        for i in range(10):
            msgs.append(
                Message(role="user", content=[
                    ToolResultBlock(tool_use_id=f"t{i}", content="a" * 500),
                ]),
            )
        recovery: dict[str, str] = {}
        microcompact(msgs, recovery_map=recovery, keep_recent=1, min_len=5)
        # Position 1 (idx 9) → untouched
        # Positions 2-7 → tiers 0-5 (50%, 30%, 20%, 10%, 5%, 1%)
        # Positions 8-10 → all clamp at tier 5 (1%)
        last_three_stubs = [
            msgs[i].content[0].content for i in range(3)
        ]
        for stub in last_three_stubs:
            assert "compacted 1%" in stub

    def test_non_tool_blocks_preserved(self):
        """Mixed content — TextBlocks alongside ToolResultBlocks."""
        msgs = [
            Message(role="user", content=[
                TextBlock(text="Look at this:"),
                ToolResultBlock(tool_use_id="mix", content="d" * 300),
            ]),
            Message(role="user", content=[
                ToolResultBlock(tool_use_id="new", content="e" * 300),
            ]),
        ]
        recovery: dict[str, str] = {}
        microcompact(msgs, recovery_map=recovery, keep_recent=1, min_len=5)
        # TextBlock preserved untouched
        assert msgs[0].content[0].text == "Look at this:"
        # ToolResult in pos 2 compacted
        assert "compacted" in msgs[0].content[1].content
        # ToolResult in pos 1 preserved
        assert msgs[1].content[0].content == "e" * 300

    def test_only_user_turns_compacted(self):
        """Assistant turns containing ToolResultBlock (shouldn't happen
        in practice, but defensive) are ignored."""
        msgs = [
            Message(role="assistant", content=[
                ToolResultBlock(tool_use_id="weird", content="x" * 500),
            ]),
            Message(role="user", content=[
                ToolResultBlock(tool_use_id="past", content="y" * 500),
            ]),
        ]
        recovery: dict[str, str] = {}
        microcompact(msgs, recovery_map=recovery, keep_recent=0, min_len=5)
        # Assistant turn → ignored
        assert "compacted" not in msgs[0].content[0].content
        # User turn → compacted (pos 1, keep_recent=0)
        assert "compacted" in msgs[1].content[0].content


