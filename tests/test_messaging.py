"""Tests for MessageBus — JSONL round-trip, broadcast, multi-recipient."""

import json
import tempfile
from pathlib import Path

from rich_senpai.core.state import MessageBus


# ── helpers ────────────────────────────────────────────────────────────


def _make_bus() -> tuple[MessageBus, Path]:
    tmp = Path(tempfile.mkdtemp())
    bus = MessageBus(inbox_dir=tmp / "inbox")
    return bus, tmp


# ── send + read_inbox round-trip ───────────────────────────────────────


def test_send_and_read_round_trip():
    bus, _ = _make_bus()
    bus.send("lead", "bob", "hello bob")
    msgs = bus.read_inbox("bob")
    assert len(msgs) == 1
    assert msgs[0]["type"] == "message"
    assert msgs[0]["from"] == "lead"
    assert msgs[0]["content"] == "hello bob"
    assert "timestamp" in msgs[0]


def test_read_inbox_drains_file():
    bus, _ = _make_bus()
    bus.send("lead", "alice", "msg1")
    bus.send("lead", "alice", "msg2")
    msgs1 = bus.read_inbox("alice")
    assert len(msgs1) == 2
    # After drain, file should be empty.
    msgs2 = bus.read_inbox("alice")
    assert msgs2 == []


def test_read_inbox_empty_for_nonexistent_recipient():
    bus, _ = _make_bus()
    msgs = bus.read_inbox("nobody")
    assert msgs == []


def test_send_preserves_message_type():
    bus, _ = _make_bus()
    bus.send("lead", "bob", "stop", msg_type="shutdown_request")
    msgs = bus.read_inbox("bob")
    assert msgs[0]["type"] == "shutdown_request"


def test_send_with_extra_fields():
    bus, _ = _make_bus()
    bus.send("lead", "carol", "need approval", extra={"request_id": "123", "action": "approve"})
    msgs = bus.read_inbox("carol")
    assert msgs[0]["request_id"] == "123"
    assert msgs[0]["action"] == "approve"


def test_multiple_recipients_isolated():
    bus, _ = _make_bus()
    bus.send("lead", "alice", "for alice")
    bus.send("lead", "bob", "for bob")
    assert len(bus.read_inbox("alice")) == 1
    assert len(bus.read_inbox("bob")) == 1


def test_send_return_value():
    bus, _ = _make_bus()
    result = bus.send("lead", "bob", "hi")
    assert "Sent message to bob" == result


def test_jsonl_format_is_valid_json_per_line():
    bus, _ = _make_bus()
    bus.send("lead", "bob", "line1")
    bus.send("lead", "bob", "line2")
    # The underlying file should have one JSON object per line.
    path = bus._path("bob")
    raw = path.read_text(encoding="utf-8")
    lines = raw.strip().split("\n")
    assert len(lines) == 2
    for line in lines:
        obj = json.loads(line)
        assert isinstance(obj, dict)


# ── broadcast ──────────────────────────────────────────────────────────


def test_broadcast_to_multiple():
    bus, _ = _make_bus()
    result = bus.broadcast("lead", "announcement", ["alice", "bob", "carol"])
    assert "Broadcast to 3 teammates" in result
    for name in ["alice", "bob", "carol"]:
        msgs = bus.read_inbox(name)
        assert len(msgs) == 1
        assert msgs[0]["type"] == "broadcast"
        assert msgs[0]["content"] == "announcement"


def test_broadcast_skips_sender():
    bus, _ = _make_bus()
    result = bus.broadcast("lead", "hello", ["lead", "bob"])
    assert "Broadcast to 1 teammates" in result
    # lead should not receive their own broadcast.
    assert bus.read_inbox("lead") == []
    assert len(bus.read_inbox("bob")) == 1


def test_broadcast_empty_list():
    bus, _ = _make_bus()
    result = bus.broadcast("lead", "nobody hears", [])
    assert "Broadcast to 0 teammates" in result


def test_broadcast_only_sender_in_list():
    bus, _ = _make_bus()
    result = bus.broadcast("lead", "solo", ["lead"])
    assert "Broadcast to 0 teammates" in result


# ── inbox_dir creation ─────────────────────────────────────────────────


def test_inbox_dir_created_on_init():
    with tempfile.TemporaryDirectory() as tmp:
        inbox = Path(tmp) / "sub" / "inbox"
        bus = MessageBus(inbox_dir=inbox)
        assert inbox.is_dir()
