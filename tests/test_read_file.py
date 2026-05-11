"""Tests for the read_file tool — cat -n format, offset/limit slicing,
tracker integration, and error paths."""

import tempfile
from pathlib import Path

from rich_senpai.tools.file_access._session import (
    ReadTracker,
    reset_tracker,
    set_tracker,
)
from rich_senpai.tools.file_access.read_file import read_file


# ── helpers ──────────────────────────────────────────────────────────────

def _write(path: Path, content: str) -> Path:
    path.write_text(content)
    return path


def _lines(n: int) -> str:
    return "\n".join(f"line {i}" for i in range(1, n + 1))


# ── cat -n output format ─────────────────────────────────────────────────


def test_output_uses_cat_n_format():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "test.txt", "alpha\nbeta\ngamma")
        result = read_file(str(f), allow_outside_workdir=True)
        assert result.ok
        # Each line prefixed with right-aligned 6-char lineno + tab.
        assert "     1\talpha" in result.text
        assert "     2\tbeta" in result.text
        assert "     3\tgamma" in result.text


def test_line_numbers_match_offset():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "test.txt", _lines(20))
        result = read_file(str(f), offset=12, limit=2, allow_outside_workdir=True)
        assert result.ok
        # Line numbers reflect the source line, not 1-based slice position.
        assert "    12\tline 12" in result.text
        assert "    13\tline 13" in result.text


# ── full-file reads ──────────────────────────────────────────────────────


def test_read_entire_file():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "test.txt", _lines(10))
        result = read_file(str(f), allow_outside_workdir=True)
        assert result.ok
        assert "(10 lines)" in result.text
        assert "line 1" in result.text
        assert "line 10" in result.text


def test_read_empty_file():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "empty.txt", "")
        result = read_file(str(f), allow_outside_workdir=True)
        assert result.ok
        assert "0 lines" in result.text


# ── offset / limit slicing ───────────────────────────────────────────────


def test_offset_and_limit():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "test.txt", _lines(100))
        result = read_file(str(f), offset=10, limit=5, allow_outside_workdir=True)
        assert result.ok
        assert "showing lines 10-14" in result.text
        for i in range(10, 15):
            assert f"line {i}" in result.text
        assert "line 9\n" not in result.text  # 9 should not appear as a row
        assert "line 15" not in result.text


def test_offset_only_reads_to_end():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "test.txt", _lines(10))
        result = read_file(str(f), offset=8, allow_outside_workdir=True)
        assert result.ok
        assert "showing lines 8-10" in result.text
        assert "line 8" in result.text
        assert "line 10" in result.text
        assert "line 7\n" not in result.text


def test_limit_only_from_start():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "test.txt", _lines(20))
        result = read_file(str(f), limit=3, allow_outside_workdir=True)
        assert result.ok
        assert "showing lines 1-3" in result.text
        assert "line 1" in result.text
        assert "line 3" in result.text
        assert "line 4" not in result.text


def test_limit_exceeds_total_shows_full_file():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "test.txt", _lines(5))
        result = read_file(str(f), limit=100, allow_outside_workdir=True)
        assert result.ok
        assert "showing lines" not in result.text
        assert "(5 lines)" in result.text


def test_offset_past_end():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "test.txt", _lines(10))
        result = read_file(str(f), offset=100, allow_outside_workdir=True)
        assert result.ok
        assert "offset past end" in result.text


def test_offset_zero_clamped_to_one():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "test.txt", _lines(5))
        result = read_file(str(f), offset=0, limit=2, allow_outside_workdir=True)
        assert result.ok
        assert "showing lines 1-2" in result.text


def test_negative_offset_clamped_to_one():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "test.txt", _lines(5))
        result = read_file(str(f), offset=-5, limit=2, allow_outside_workdir=True)
        assert result.ok
        assert "showing lines 1-2" in result.text


def test_single_line_slice():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "test.txt", _lines(5))
        result = read_file(str(f), offset=3, limit=1, allow_outside_workdir=True)
        assert result.ok
        assert "showing lines 3-3" in result.text
        assert result.text.endswith("line 3")


# ── session tracker integration ──────────────────────────────────────────


def test_read_marks_file_in_tracker():
    tracker = ReadTracker()
    token = set_tracker(tracker)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            f = _write(Path(tmp) / "test.txt", "hello")
            assert not tracker.was_read(f)
            result = read_file(str(f), allow_outside_workdir=True)
            assert result.ok
            assert tracker.was_read(f)
    finally:
        reset_tracker(token)


def test_no_tracker_set_is_noop():
    # Default contextvar state — no tracker installed.
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "test.txt", "hello")
        result = read_file(str(f), allow_outside_workdir=True)
        assert result.ok  # tools work fine without a tracker


# ── error paths ──────────────────────────────────────────────────────────


def test_file_not_found():
    result = read_file("/tmp/__nonexistent_rich_senpai_test__", allow_outside_workdir=True)
    assert not result.ok
    assert "file not found" in result.text


def test_directory_not_file():
    with tempfile.TemporaryDirectory() as tmp:
        result = read_file(tmp, allow_outside_workdir=True)
        assert not result.ok
        assert "not a regular file" in result.text


def test_unicode_decode_error():
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "binary.bin"
        f.write_bytes(b"\x80\x81\x82")
        result = read_file(str(f), allow_outside_workdir=True)
        assert not result.ok
        assert "could not decode" in result.text
