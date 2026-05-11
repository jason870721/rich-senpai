"""Tests for the edit_file tool — string-replace semantics, replace_all,
session read-first gate, and error paths."""

import tempfile
from pathlib import Path

from rich_senpai.tools.file_access._session import (
    ReadTracker,
    reset_tracker,
    set_tracker,
)
from rich_senpai.tools.file_access.edit_file import edit_file


# ── helpers ──────────────────────────────────────────────────────────────


def _write(path: Path, content: str) -> Path:
    path.write_text(content)
    return path


# ── happy path ───────────────────────────────────────────────────────────


def test_single_match_replaced():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "f.txt", "alpha beta gamma")
        result = edit_file(str(f), "beta", "BETA", allow_outside_workdir=True)
        assert result.ok
        assert f.read_text() == "alpha BETA gamma"
        # Returns a unified diff for TUI rendering.
        assert f"a/{f}" in result.text
        assert "-beta" in result.text or "alpha beta gamma" in result.text
        assert "+" in result.text


def test_multiline_old_and_new():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "f.txt", "one\ntwo\nthree\n")
        result = edit_file(
            str(f),
            "one\ntwo\n",
            "ONE\nTWO\nEXTRA\n",
            allow_outside_workdir=True,
        )
        assert result.ok
        assert f.read_text() == "ONE\nTWO\nEXTRA\nthree\n"


def test_whitespace_fidelity_tabs_vs_spaces():
    with tempfile.TemporaryDirectory() as tmp:
        # Source uses a tab; old_string with spaces should NOT match.
        f = _write(Path(tmp) / "f.txt", "if x:\n\treturn 1\n")
        result = edit_file(
            str(f),
            "    return 1",
            "    return 42",
            allow_outside_workdir=True,
        )
        assert not result.ok
        assert "not found" in result.text
        assert f.read_text() == "if x:\n\treturn 1\n"  # untouched


def test_trailing_whitespace_preserved():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "f.txt", "foo   \nbar\n")
        result = edit_file(str(f), "bar", "BAR", allow_outside_workdir=True)
        assert result.ok
        # Trailing spaces on the first line survive.
        assert f.read_text() == "foo   \nBAR\n"


# ── replace_all ──────────────────────────────────────────────────────────


def test_replace_all_replaces_every_occurrence():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "f.txt", "x x x y x")
        result = edit_file(
            str(f), "x", "X",
            replace_all=True,
            allow_outside_workdir=True,
        )
        assert result.ok
        assert f.read_text() == "X X X y X"
        assert "replaced 4 occurrences" in result.text


def test_replace_all_single_match_does_not_annotate_count():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "f.txt", "alpha")
        result = edit_file(
            str(f), "alpha", "ALPHA",
            replace_all=True,
            allow_outside_workdir=True,
        )
        assert result.ok
        assert f.read_text() == "ALPHA"
        assert "replaced 1 occurrences" not in result.text


def test_multiple_matches_without_replace_all_refused():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "f.txt", "x x x")
        result = edit_file(str(f), "x", "Y", allow_outside_workdir=True)
        assert not result.ok
        assert "matches 3 locations" in result.text
        assert "replace_all=true" in result.text
        assert f.read_text() == "x x x"  # untouched


# ── error paths ──────────────────────────────────────────────────────────


def test_old_string_not_found():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "f.txt", "hello world")
        result = edit_file(str(f), "goodbye", "hi", allow_outside_workdir=True)
        assert not result.ok
        assert "not found" in result.text
        assert "re-read" in result.text.lower()
        assert f.read_text() == "hello world"


def test_identical_old_and_new_refused():
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "f.txt", "alpha")
        result = edit_file(str(f), "alpha", "alpha", allow_outside_workdir=True)
        assert not result.ok
        assert "identical" in result.text
        assert f.read_text() == "alpha"


def test_file_not_found():
    result = edit_file(
        "/tmp/__nonexistent_rich_senpai_edit_test__",
        "a", "b",
        allow_outside_workdir=True,
    )
    assert not result.ok
    assert "file not found" in result.text


def test_directory_not_file():
    with tempfile.TemporaryDirectory() as tmp:
        result = edit_file(tmp, "a", "b", allow_outside_workdir=True)
        assert not result.ok
        assert "not a regular file" in result.text


# ── session read-first gate ──────────────────────────────────────────────


def test_edit_without_prior_read_refused():
    tracker = ReadTracker()
    token = set_tracker(tracker)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            f = _write(Path(tmp) / "f.txt", "hello")
            result = edit_file(str(f), "hello", "hi", allow_outside_workdir=True)
            assert not result.ok
            assert "must use read_file" in result.text
            assert f.read_text() == "hello"
    finally:
        reset_tracker(token)


def test_edit_after_read_succeeds():
    tracker = ReadTracker()
    token = set_tracker(tracker)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            f = _write(Path(tmp) / "f.txt", "hello")
            tracker.mark_read(f)
            result = edit_file(str(f), "hello", "hi", allow_outside_workdir=True)
            assert result.ok
            assert f.read_text() == "hi"
    finally:
        reset_tracker(token)


def test_no_tracker_skips_gate():
    # No tracker installed in this contextvar slot.
    with tempfile.TemporaryDirectory() as tmp:
        f = _write(Path(tmp) / "f.txt", "hello")
        result = edit_file(str(f), "hello", "hi", allow_outside_workdir=True)
        assert result.ok
        assert f.read_text() == "hi"


def test_successful_edit_marks_file_as_read():
    tracker = ReadTracker()
    token = set_tracker(tracker)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            f = _write(Path(tmp) / "f.txt", "v1")
            tracker.mark_read(f)
            assert edit_file(str(f), "v1", "v2", allow_outside_workdir=True).ok
            # Second edit doesn't require an explicit re-read.
            assert edit_file(str(f), "v2", "v3", allow_outside_workdir=True).ok
            assert f.read_text() == "v3"
    finally:
        reset_tracker(token)
