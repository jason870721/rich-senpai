"""Tests for background_run and check_background tools.

Uses a fresh BackgroundManager per test to avoid shared-state
interference between tests.

The tool functions are imported lazily to avoid a circular import:
importing background_run triggers core.state → tool_register which
scans all tool modules for SPEC; if we are the first to import
background_run the module will be partially initialized.
"""
import time

import pytest

from rich_senpai.core.unit.manager.background import (
    BackgroundManager,
    _truncate_with_marker,
)


# import helpers (do NOT import background_run/check_background at module level)
def _br():
    from rich_senpai.tools.shell.background_run import background_run
    return background_run


def _cb():
    from rich_senpai.tools.shell.check_background import check_background
    return check_background


@pytest.fixture
def bg() -> BackgroundManager:
    """Fresh BackgroundManager injected into state.BG."""
    import rich_senpai.core.state as s
    old = s.BG
    mgr = BackgroundManager()
    s.BG = mgr
    yield mgr
    mgr.shutdown()
    s.BG = old


# ── _truncate_with_marker (pure function) ───────────────────────────

class TestTruncateWithMarker:
    def test_short_text_passed_through(self):
        assert _truncate_with_marker("hi", 100, suffix_hint=".") == "hi"

    def test_exact_length_passed_through(self):
        assert _truncate_with_marker("abc", 3, suffix_hint=".") == "abc"

    def test_longer_text_truncated(self):
        result = _truncate_with_marker("hello world", 5, suffix_hint=" cut")
        assert result == "hello\n... (+6 more chars cut)"

    def test_empty_string(self):
        assert _truncate_with_marker("", 10, suffix_hint=".") == ""


# ── background_run ──────────────────────────────────────────────────

class TestBackgroundRun:
    def test_returns_task_id_and_started(self, bg):
        result = _br()("echo hello")
        assert result.ok
        assert result.text.startswith("task_id=")
        assert "started: echo hello" in result.text

    def test_task_id_is_short_hex(self, bg):
        result = _br()("true")
        tid = result.text.split("\n")[0].split("=", 1)[1]
        assert len(tid) == 8

    def test_each_call_generates_unique_id(self, bg):
        r1 = _br()("true")
        r2 = _br()("true")
        tid1 = r1.text.split("\n")[0].split("=", 1)[1]
        tid2 = r2.text.split("\n")[0].split("=", 1)[1]
        assert tid1 != tid2

    def test_custom_timeout_accepted(self, bg):
        result = _br()("echo x", timeout=60)
        assert result.ok

    def test_long_command_truncated_in_started_message(self, bg):
        long_cmd = "echo " + "x" * 100
        result = _br()(long_cmd)
        assert "started:" in result.text
        assert len(result.text.split("started: ", 1)[1]) <= 80


# ── check_background ────────────────────────────────────────────────

class TestCheckBackground:
    def test_unknown_task_id_returns_error(self, bg):
        result = _cb()("deadbeef")
        assert not result.ok
        assert result.text.startswith("Unknown background task: deadbeef")

    def test_empty_state_returns_no_tasks(self, bg):
        result = _cb()()
        assert result.ok
        assert result.text == "No bg tasks."

    def test_list_all_tasks_shows_running(self, bg):
        r = _br()("sleep 2")
        tid = r.text.split("\n")[0].split("=", 1)[1]
        result = _cb()()
        assert result.ok
        assert tid in result.text
        assert "[running]" in result.text

    def test_task_completes_and_shows_output(self, bg):
        r = _br()("echo done")
        tid = r.text.split("\n")[0].split("=", 1)[1]
        _wait_for_task(bg, tid, timeout=5)
        result = _cb()(tid)
        assert result.ok
        assert "[completed]" in result.text
        assert "done" in result.text

    def test_task_that_fails_shows_error_status(self, bg):
        r = _br()("exit 2")
        tid = r.text.split("\n")[0].split("=", 1)[1]
        _wait_for_task(bg, tid, timeout=5)
        result = _cb()(tid)
        assert result.ok
        assert "[completed]" in result.text or "[error]" in result.text

    def test_task_timeout_shows_error(self, bg):
        r = _br()("sleep 10", timeout=1)
        tid = r.text.split("\n")[0].split("=", 1)[1]
        _wait_for_task(bg, tid, timeout=5)
        result = _cb()(tid)
        assert result.ok
        assert "[error]" in result.text
        assert "timeout" in result.text.lower()

    def test_multiple_tasks_listed(self, bg):
        _br()("sleep 1")
        _br()("sleep 1")
        result = _cb()()
        assert result.ok
        lines = result.text.strip().split("\n")
        assert len(lines) >= 2


# ── drain ───────────────────────────────────────────────────────────

class TestDrain:
    def test_drain_returns_notifications_after_completion(self, bg):
        r = _br()("echo boom")
        tid = r.text.split("\n")[0].split("=", 1)[1]
        _wait_for_task(bg, tid, timeout=5)
        notifs = bg.drain()
        assert len(notifs) >= 1
        assert notifs[0]["task_id"] == tid
        assert notifs[0]["status"] == "completed"

    def test_drain_empties_queue(self, bg):
        _br()("echo first")
        _br()("echo second")
        time.sleep(0.5)
        bg.drain()  # consume first wave
        # Second drain should be empty or nearly so
        remaining = bg.drain()
        assert remaining == []


# ── reset ───────────────────────────────────────────────────────────

class TestReset:
    def test_reset_clears_all_tasks(self, bg):
        _br()("echo x")
        bg.reset()
        result = _cb()()
        assert result.ok
        assert result.text == "No bg tasks."

    def test_reset_clears_notifications(self, bg):
        _br()("echo x")
        bg.reset()
        assert bg.drain() == []


# ── helpers ─────────────────────────────────────────────────────────

def _wait_for_task(bg: BackgroundManager, tid: str, timeout: float = 5) -> None:
    """Poll until *tid* is no longer 'running' or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with bg._lock:
            t = bg.tasks.get(tid)
            if t and t["status"] != "running":
                return
        time.sleep(0.05)
    raise TimeoutError(f"Task {tid} did not finish within {timeout}s")
