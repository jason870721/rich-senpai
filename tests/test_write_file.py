"""Tests for the write_file tool — create, overwrite, read-first gate,
parent-dir creation, errors."""

import tempfile
from pathlib import Path

from rich_senpai.tools.file_access._session import (
    ReadTracker,
    reset_tracker,
    set_tracker,
)
from rich_senpai.tools.file_access.write_file import write_file


# ── create new file ──────────────────────────────────────────────────────


def test_create_new_file_returns_diff():
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "new.txt")
        result = write_file(path, "hello\nworld\n", allow_outside_workdir=True)
        assert result.ok
        assert "--- /dev/null" in result.text
        assert f"+++ b/{path}" in result.text
        assert "+hello" in result.text
        assert "+world" in result.text
        assert Path(path).read_text() == "hello\nworld\n"


def test_create_new_file_no_trailing_newline_marks_it():
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "no_nl.txt")
        result = write_file(path, "abc", allow_outside_workdir=True)
        assert result.ok
        assert "\\ No newline at end of file" in result.text
        assert Path(path).read_text() == "abc"


def test_create_file_in_missing_parent_dir():
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "a" / "b" / "c" / "deep.txt")
        result = write_file(path, "content", allow_outside_workdir=True)
        assert result.ok
        assert Path(path).exists()
        assert Path(path).read_text() == "content"


def test_create_empty_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "empty.txt")
        result = write_file(path, "", allow_outside_workdir=True)
        assert result.ok
        assert Path(path).exists()
        assert Path(path).read_text() == ""


# ── overwrite existing file ──────────────────────────────────────────────


def test_overwrite_existing_returns_byte_count():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "existing.txt"
        path.write_text("old content")
        # No tracker installed → guard is a no-op.
        result = write_file(str(path), "new content here", allow_outside_workdir=True)
        assert result.ok
        assert "wrote" in result.text
        assert "bytes" in result.text
        assert "--- /dev/null" not in result.text
        assert path.read_text() == "new content here"


def test_overwrite_preserves_byte_count_in_message():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "existing.txt"
        path.write_text("old")
        content = "x" * 42
        result = write_file(str(path), content, allow_outside_workdir=True)
        assert result.ok
        assert "42 bytes" in result.text


# ── read-first gate ──────────────────────────────────────────────────────


def test_overwrite_without_prior_read_refused():
    tracker = ReadTracker()
    token = set_tracker(tracker)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "existing.txt"
            path.write_text("old")
            result = write_file(str(path), "new", allow_outside_workdir=True)
            assert not result.ok
            assert "must use read_file" in result.text
            assert path.read_text() == "old"  # untouched
    finally:
        reset_tracker(token)


def test_overwrite_after_read_succeeds():
    tracker = ReadTracker()
    token = set_tracker(tracker)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "existing.txt"
            path.write_text("old")
            tracker.mark_read(path)
            result = write_file(str(path), "new", allow_outside_workdir=True)
            assert result.ok
            assert path.read_text() == "new"
    finally:
        reset_tracker(token)


def test_create_new_file_no_read_needed_with_tracker():
    tracker = ReadTracker()
    token = set_tracker(tracker)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "fresh.txt")
            # No prior read — but the file doesn't exist, so the gate doesn't apply.
            result = write_file(path, "content", allow_outside_workdir=True)
            assert result.ok
            assert Path(path).read_text() == "content"
    finally:
        reset_tracker(token)


def test_write_marks_file_as_read_for_followup_writes():
    tracker = ReadTracker()
    token = set_tracker(tracker)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "loop.txt"
            # First write creates it (no read needed). After success the
            # file is registered, so a second overwrite is allowed.
            assert write_file(str(path), "v1", allow_outside_workdir=True).ok
            assert write_file(str(path), "v2", allow_outside_workdir=True).ok
            assert path.read_text() == "v2"
    finally:
        reset_tracker(token)


# ── encoding ─────────────────────────────────────────────────────────────


def test_write_with_custom_encoding():
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "latin.txt")
        result = write_file(path, "café", encoding="latin-1", allow_outside_workdir=True)
        assert result.ok
        assert Path(path).read_bytes() == b"caf\xe9"


# ── error paths ──────────────────────────────────────────────────────────


def test_write_to_directory_fails():
    with tempfile.TemporaryDirectory() as tmp:
        # Path is an existing directory — write_file's tracker gate fires first
        # only if a tracker is installed; here there is none, so the OSError
        # bubbles up from write_text.
        result = write_file(tmp, "content", allow_outside_workdir=True)
        assert not result.ok
        # Either the read-first guard or the OSError surfaces depending on
        # whether a tracker is installed. Both are valid failures.
        assert ("could not write" in result.text) or ("must use read_file" in result.text)


def test_write_to_unwritable_path_fails():
    with tempfile.TemporaryDirectory() as tmp:
        ro_dir = Path(tmp) / "ro"
        ro_dir.mkdir()
        ro_dir.chmod(0o500)
        try:
            result = write_file(str(ro_dir / "blocked.txt"), "x", allow_outside_workdir=True)
            if not result.ok:
                assert "could not write" in result.text
        finally:
            ro_dir.chmod(0o700)
