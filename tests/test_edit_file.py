"""Tests for edit_file — diff parse, apply, header synthesis, error paths."""

import tempfile
from pathlib import Path

from rich_senpai.tools.file_access.edit_file import edit_file


def _write(path: Path, content: str) -> Path:
    path.write_text(content)
    return path


# ── happy paths ──────────────────────────────────────────────────────────


def test_single_hunk_replacement():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "f.txt", "line a\nline b\nline c\n")
        diff = (
            "@@ -1,3 +1,3 @@\n"
            " line a\n"
            "-line b\n"
            "+line B!\n"
            " line c\n"
        )
        result = edit_file(str(f), diff)
        assert result.ok
        assert f.read_text() == "line a\nline B!\nline c\n"
        # Synthesized headers should be present
        assert f"--- a/{f}" in result.text
        assert f"+++ b/{f}" in result.text


def test_pure_addition_hunk():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "f.txt", "first\nsecond\n")
        diff = (
            "@@ -1,2 +1,3 @@\n"
            " first\n"
            "+inserted\n"
            " second\n"
        )
        result = edit_file(str(f), diff)
        assert result.ok
        assert f.read_text() == "first\ninserted\nsecond\n"


def test_pure_removal_hunk():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "f.txt", "one\ntwo\nthree\n")
        diff = (
            "@@ -1,3 +1,2 @@\n"
            " one\n"
            "-two\n"
            " three\n"
        )
        result = edit_file(str(f), diff)
        assert result.ok
        assert f.read_text() == "one\nthree\n"


def test_multiple_hunks_in_one_diff():
    with tempfile.TemporaryDirectory() as tmp:
        original = "a\nb\nc\nd\ne\nf\ng\n"
        f = _write(Path(tmp) / "f.txt", original)
        diff = (
            "@@ -1,3 +1,3 @@\n"
            " a\n"
            "-b\n"
            "+B\n"
            " c\n"
            "@@ -5,3 +5,3 @@\n"
            " e\n"
            "-f\n"
            "+F\n"
            " g\n"
        )
        result = edit_file(str(f), diff)
        assert result.ok
        assert f.read_text() == "a\nB\nc\nd\ne\nF\ng\n"


def test_advisory_counts_recounted():
    """Header counts are advisory; the parser auto-recounts from body."""
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "f.txt", "x\ny\nz\n")
        # Header says ",99 ,99" but body is what counts.
        diff = (
            "@@ -1,99 +1,99 @@\n"
            " x\n"
            "-y\n"
            "+Y\n"
            " z\n"
        )
        result = edit_file(str(f), diff)
        assert result.ok
        assert f.read_text() == "x\nY\nz\n"


def test_diff_with_existing_file_headers_passes_through():
    """Agent may paste a diff with `--- a/` / `+++ b/` already there."""
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "f.txt", "alpha\nbeta\n")
        diff = (
            f"--- a/{f}\n"
            f"+++ b/{f}\n"
            "@@ -1,2 +1,2 @@\n"
            "-alpha\n"
            "+ALPHA\n"
            " beta\n"
        )
        result = edit_file(str(f), diff)
        assert result.ok
        assert f.read_text() == "ALPHA\nbeta\n"
        # Header should not be double-prefixed
        assert result.text.count("--- a/") == 1


# ── error paths ──────────────────────────────────────────────────────────


def test_missing_file():
    diff = "@@ -1,1 +1,1 @@\n-old\n+new\n"
    result = edit_file("/tmp/__nonexistent_rich_senpai_edit__", diff)
    assert not result.ok
    assert "file not found" in result.text


def test_directory_not_file():
    with tempfile.TemporaryDirectory() as tmp:
        diff = "@@ -1,1 +1,1 @@\n-old\n+new\n"
        result = edit_file(tmp, diff)
        assert not result.ok
        assert "not a regular file" in result.text


def test_empty_diff_parse_error():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "f.txt", "a\n")
        result = edit_file(str(f), "")
        assert not result.ok
        assert "parse failed" in result.text


def test_malformed_diff_no_hunk_header():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "f.txt", "a\nb\n")
        result = edit_file(str(f), "this is not a diff at all\n")
        assert not result.ok
        assert "parse failed" in result.text


def test_context_mismatch_apply_error():
    """Context line doesn't match the file — fails with a targeted error."""
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "f.txt", "actual\nbeta\n")
        diff = (
            "@@ -1,2 +1,2 @@\n"
            " wrong context\n"
            "-beta\n"
            "+BETA\n"
        )
        result = edit_file(str(f), diff)
        assert not result.ok
        assert "apply failed" in result.text
        # Per the SPEC, mismatch errors should tell the agent to re-read.
        assert "Re-read" in result.text or "re-read" in result.text


def test_removal_mismatch_apply_error():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "f.txt", "x\ny\n")
        diff = (
            "@@ -1,2 +1,2 @@\n"
            " x\n"
            "-NOT_Y\n"
            "+Y\n"
        )
        result = edit_file(str(f), diff)
        assert not result.ok
        assert "apply failed" in result.text


def test_file_unchanged_on_apply_failure():
    """A failed apply must not corrupt the file."""
    with tempfile.TemporaryDirectory() as tmp:
        original = "preserve\nme\n"
        f = _write(Path(tmp) / "f.txt", original)
        diff = (
            "@@ -1,2 +1,2 @@\n"
            "-bogus\n"
            "+nope\n"
            " me\n"
        )
        result = edit_file(str(f), diff)
        assert not result.ok
        assert f.read_text() == original
