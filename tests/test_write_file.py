"""Tests for the write_file tool — create, overwrite, parent-dir creation, errors."""

import tempfile
from pathlib import Path

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
        result = write_file(str(path), "new content here", allow_outside_workdir=True)
        assert result.ok
        assert "wrote" in result.text
        assert "bytes" in result.text
        assert "--- /dev/null" not in result.text  # no diff on overwrite
        assert path.read_text() == "new content here"


def test_overwrite_preserves_byte_count_in_message():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "existing.txt"
        path.write_text("old")
        content = "x" * 42
        result = write_file(str(path), content, allow_outside_workdir=True)
        assert result.ok
        assert "42 bytes" in result.text


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
        # Writing where a directory already exists by that name should fail.
        result = write_file(tmp, "content", allow_outside_workdir=True)
        assert not result.ok
        assert "could not write" in result.text


def test_write_to_unwritable_path_fails():
    with tempfile.TemporaryDirectory() as tmp:
        ro_dir = Path(tmp) / "ro"
        ro_dir.mkdir()
        ro_dir.chmod(0o500)  # r-x: cannot create children
        try:
            result = write_file(str(ro_dir / "blocked.txt"), "x", allow_outside_workdir=True)
            # On some filesystems (e.g. running as root) this may still
            # succeed; only assert when it genuinely failed.
            if not result.ok:
                assert "could not write" in result.text
        finally:
            ro_dir.chmod(0o700)  # restore for cleanup
