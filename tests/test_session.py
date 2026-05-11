"""Tests for the per-conversation file-access ReadTracker."""

import asyncio
import os
import tempfile
from pathlib import Path

from rich_senpai.tools.file_access._session import (
    ReadTracker,
    get_tracker,
    reset_tracker,
    set_tracker,
)


# ── ReadTracker basics ───────────────────────────────────────────────────


def test_mark_and_was_read():
    t = ReadTracker()
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "a.txt"
        f.write_text("hi")
        assert not t.was_read(f)
        t.mark_read(f)
        assert t.was_read(f)


def test_resolves_paths_so_dot_dot_matches():
    t = ReadTracker()
    with tempfile.TemporaryDirectory() as tmp:
        sub = Path(tmp) / "sub"
        sub.mkdir()
        f = sub / "a.txt"
        f.write_text("hi")
        t.mark_read(f)
        # An equivalent path via .. should still hit.
        round_about = sub / ".." / "sub" / "a.txt"
        assert t.was_read(round_about)


def test_clear_drops_everything():
    t = ReadTracker()
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "a.txt"
        f.write_text("hi")
        t.mark_read(f)
        assert t.was_read(f)
        t.clear()
        assert not t.was_read(f)


# ── contextvar plumbing ─────────────────────────────────────────────────


def test_default_tracker_is_none():
    assert get_tracker() is None


def test_set_and_reset_tracker():
    t = ReadTracker()
    token = set_tracker(t)
    try:
        assert get_tracker() is t
    finally:
        reset_tracker(token)
    assert get_tracker() is None


def test_isolated_trackers_across_async_tasks():
    """Each asyncio.Task gets its own copy of the contextvar, so two
    concurrent agents can install different trackers without interfering."""

    async def worker(my_tracker: ReadTracker, seen: dict[str, object]):
        token = set_tracker(my_tracker)
        try:
            # Yield control so both workers interleave.
            await asyncio.sleep(0)
            seen["tracker"] = get_tracker()
        finally:
            reset_tracker(token)

    async def main():
        t_a = ReadTracker()
        t_b = ReadTracker()
        seen_a: dict[str, object] = {}
        seen_b: dict[str, object] = {}
        await asyncio.gather(
            worker(t_a, seen_a),
            worker(t_b, seen_b),
        )
        return seen_a, seen_b

    seen_a, seen_b = asyncio.run(main())
    assert seen_a["tracker"] is not seen_b["tracker"]
    assert isinstance(seen_a["tracker"], ReadTracker)
    assert isinstance(seen_b["tracker"], ReadTracker)


def test_symlink_resolution(tmp_path):
    """A file reached via a symlink should be considered the same as the
    file reached via the canonical path."""
    real = tmp_path / "real.txt"
    real.write_text("hi")
    link = tmp_path / "link.txt"
    try:
        os.symlink(real, link)
    except (OSError, NotImplementedError):
        # Filesystems that disallow symlinks (e.g. some Windows setups);
        # the canonical-path semantics still apply on posix.
        return
    t = ReadTracker()
    t.mark_read(link)
    assert t.was_read(real)
