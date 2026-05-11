"""Tests for the read_file tool — full reads, offset/limit slicing, and error paths."""

import tempfile
from pathlib import Path

from rich_senpai.tools.file_access.read_file import read_file


# ── helpers ──────────────────────────────────────────────────────────────

def _write(path: Path, content: str) -> Path:
    path.write_text(content)
    return path


def _lines(n: int) -> str:
    """Generate a test file with N lines like 'line 1', 'line 2', etc."""
    return "\n".join(f"line {i}" for i in range(1, n + 1))


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
        assert "line 10\nline 11\nline 12\nline 13\nline 14" in result.text
        assert "line 9" not in result.text
        assert "line 15" not in result.text


def test_offset_only_reads_to_end():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "test.txt", _lines(10))
        result = read_file(str(f), offset=8, allow_outside_workdir=True)
        assert result.ok
        assert "showing lines 8-10" in result.text
        assert "line 8" in result.text
        assert "line 10" in result.text
        assert "line 7" not in result.text


def test_limit_only_from_start():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "test.txt", _lines(20))
        result = read_file(str(f), limit=3, allow_outside_workdir=True)
        assert result.ok
        # offset defaults to 1 and limit=3 < total → slice
        assert "showing lines 1-3" in result.text
        assert "line 1" in result.text
        assert "line 3" in result.text
        assert "line 4" not in result.text


def test_limit_exceeds_total_shows_full_file():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "test.txt", _lines(5))
        result = read_file(str(f), limit=100, allow_outside_workdir=True)
        assert result.ok
        # start=0, end=5 → full read, no "showing lines" suffix
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
