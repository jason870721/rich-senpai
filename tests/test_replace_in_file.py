"""Tests for replace_in_file — single replacement, ambiguity & not-found errors."""

import tempfile
from pathlib import Path

from rich_senpai.tools.file_access.replace_in_file import replace_in_file


def _write(path: Path, content: str) -> Path:
    path.write_text(content)
    return path


# ── happy path ───────────────────────────────────────────────────────────


def test_single_replacement():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "f.txt", "alpha\nbeta\ngamma\n")
        result = replace_in_file(str(f), "beta", "BETA", allow_outside_workdir=True)
        assert result.ok
        assert f.read_text() == "alpha\nBETA\ngamma\n"
        # Result is a unified diff
        assert "-beta" in result.text
        assert "+BETA" in result.text


def test_replacement_with_multiline_old_str():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "f.txt", "one\ntwo\nthree\n")
        result = replace_in_file(str(f), "one\ntwo\n", "ONE\nTWO\n", allow_outside_workdir=True)
        assert result.ok
        assert f.read_text() == "ONE\nTWO\nthree\n"


def test_replacement_collapses_lines():
    """new_str shorter than old_str — file shrinks."""
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "f.txt", "header\na\nb\nc\nfooter\n")
        result = replace_in_file(str(f), "a\nb\nc\n", "merged\n", allow_outside_workdir=True)
        assert result.ok
        assert f.read_text() == "header\nmerged\nfooter\n"


def test_replacement_expands_lines():
    """new_str longer than old_str — file grows."""
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "f.txt", "x\nmid\ny\n")
        result = replace_in_file(str(f), "mid\n", "mid1\nmid2\nmid3\n", allow_outside_workdir=True)
        assert result.ok
        assert f.read_text() == "x\nmid1\nmid2\nmid3\ny\n"


# ── ambiguity / not found ────────────────────────────────────────────────


def test_no_match_fails_with_helpful_message():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "f.txt", "alpha\nbeta\n")
        result = replace_in_file(str(f), "missing", "x", allow_outside_workdir=True)
        assert not result.ok
        assert "not found" in result.text
        # File untouched
        assert f.read_text() == "alpha\nbeta\n"


def test_ambiguous_match_fails():
    """If old_str appears more than once, the tool refuses to guess."""
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "f.txt", "dup\nother\ndup\n")
        result = replace_in_file(str(f), "dup", "X", allow_outside_workdir=True)
        assert not result.ok
        assert "matches" in result.text and "2" in result.text
        assert "unique" in result.text or "context" in result.text
        # File untouched
        assert f.read_text() == "dup\nother\ndup\n"


def test_ambiguous_resolved_by_adding_context():
    """The agent's documented workaround for ambiguity is to add context."""
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "f.txt", "dup\nother\ndup\n")
        result = replace_in_file(str(f), "other\ndup\n", "other\nUNIQUE\n", allow_outside_workdir=True)
        assert result.ok
        assert f.read_text() == "dup\nother\nUNIQUE\n"


# ── error paths ──────────────────────────────────────────────────────────


def test_missing_file():
    result = replace_in_file("/tmp/__nonexistent_rich_senpai_replace__", "a", "b", allow_outside_workdir=True)
    assert not result.ok
    assert "file not found" in result.text


def test_directory_not_file():
    with tempfile.TemporaryDirectory() as tmp:
        result = replace_in_file(tmp, "a", "b", allow_outside_workdir=True)
        assert not result.ok
        assert "not a regular file" in result.text


def test_binary_file_decode_error():
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "bin"
        f.write_bytes(b"\x80\x81\x82")
        result = replace_in_file(str(f), "anything", "x", allow_outside_workdir=True)
        assert not result.ok
        assert "could not read" in result.text
