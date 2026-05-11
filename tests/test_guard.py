"""Path-traversal guard tests.

Tests that all four file-access tools deny access outside WORKDIR
by default and allow it when opt-in flag is set.
"""

import tempfile
from pathlib import Path

import pytest

from rich_senpai.tools.file_access._guard import (
    PathOutsideWorkdirError,
    _is_within,
    resolve_safe,
)
from rich_senpai.tools.file_access.edit_file import edit_file
from rich_senpai.tools.file_access.read_file import read_file
from rich_senpai.tools.file_access.replace_in_file import replace_in_file
from rich_senpai.tools.file_access.write_file import write_file


class TestIsWithin:
    def test_child_inside_parent(self):
        assert _is_within(Path("/a/b/c"), Path("/a"))

    def test_equal_paths_is_within(self):
        assert _is_within(Path("/a/b"), Path("/a/b"))

    def test_child_outside_parent(self):
        assert not _is_within(Path("/a/b"), Path("/a/c"))

    def test_partial_prefix_not_fooled(self):
        assert not _is_within(Path("/a/bb"), Path("/a/b"))


class TestResolveSafe:
    def test_relative_path_resolves_within_workdir(self, monkeypatch, tmp_path):
        monkeypatch.setattr("rich_senpai.tools.file_access._guard.config.WORKDIR", tmp_path)
        (tmp_path / "sub" / "file.txt").mkdir(parents=True)
        result = resolve_safe("sub/file.txt")
        assert result == (tmp_path / "sub" / "file.txt").resolve()

    def test_absolute_path_within_workdir(self, monkeypatch, tmp_path):
        monkeypatch.setattr("rich_senpai.tools.file_access._guard.config.WORKDIR", tmp_path)
        (tmp_path / "ok.txt").write_text("hi")
        result = resolve_safe(str(tmp_path / "ok.txt"))
        assert result == (tmp_path / "ok.txt").resolve()

    def test_path_outside_workdir_raises(self, monkeypatch, tmp_path):
        monkeypatch.setattr("rich_senpai.tools.file_access._guard.config.WORKDIR", tmp_path)
        outside = Path(tempfile.gettempdir()) / "outside.txt"
        with pytest.raises(PathOutsideWorkdirError) as exc:
            resolve_safe(str(outside))
        assert "outside the workdir" in str(exc.value)

    def test_allow_outside_workdir_bypasses_guard(self, monkeypatch, tmp_path):
        monkeypatch.setattr("rich_senpai.tools.file_access._guard.config.WORKDIR", tmp_path)
        outside = Path(tempfile.gettempdir()) / "bypass.txt"
        result = resolve_safe(str(outside), allow_outside_workdir=True)
        assert result == outside.resolve()


class TestReadFileGuard:
    def test_outside_workdir_denied(self, monkeypatch, tmp_path):
        monkeypatch.setattr("rich_senpai.tools.file_access._guard.config.WORKDIR", tmp_path)
        outside = Path(tempfile.gettempdir())
        result = read_file(str(outside))
        assert not result.ok
        assert "outside the workdir" in result.text

    def test_allow_outside_workdir_bypasses(self, monkeypatch, tmp_path):
        monkeypatch.setattr("rich_senpai.tools.file_access._guard.config.WORKDIR", tmp_path)
        outside = Path(tempfile.gettempdir())
        result = read_file(str(outside), allow_outside_workdir=True)
        # Will fail with "file not found" or "not a regular file" — not guard
        assert "outside the workdir" not in result.text


class TestWriteFileGuard:
    def test_outside_workdir_denied(self, monkeypatch, tmp_path):
        monkeypatch.setattr("rich_senpai.tools.file_access._guard.config.WORKDIR", tmp_path)
        outside = Path(tempfile.gettempdir()) / "forbidden.txt"
        result = write_file(str(outside), "content")
        assert not result.ok
        assert "outside the workdir" in result.text

    def test_allow_outside_workdir_bypasses(self, monkeypatch, tmp_path):
        monkeypatch.setattr("rich_senpai.tools.file_access._guard.config.WORKDIR", tmp_path)
        outside = Path(tempfile.gettempdir()) / "allowed.txt"
        try:
            result = write_file(str(outside), "content", allow_outside_workdir=True)
            assert result.ok
        finally:
            outside.unlink(missing_ok=True)


class TestEditFileGuard:
    def test_outside_workdir_denied(self, monkeypatch, tmp_path):
        monkeypatch.setattr("rich_senpai.tools.file_access._guard.config.WORKDIR", tmp_path)
        outside = Path(tempfile.gettempdir()) / "nope.txt"
        result = edit_file(str(outside), "@@ -1,0 +1 @@\n+hi\n")
        assert not result.ok
        assert "outside the workdir" in result.text

    def test_allow_outside_workdir_bypasses(self, monkeypatch, tmp_path):
        monkeypatch.setattr("rich_senpai.tools.file_access._guard.config.WORKDIR", tmp_path)
        outside = Path(tempfile.gettempdir()) / "ok_edit.txt"
        try:
            # Create file first via python
            outside.write_text("line\n")
            result = edit_file(
                str(outside),
                "@@ -1 +1 @@\n-line\n+changed\n",
                allow_outside_workdir=True,
            )
            assert result.ok
        finally:
            outside.unlink(missing_ok=True)


class TestReplaceInFileGuard:
    def test_outside_workdir_denied(self, monkeypatch, tmp_path):
        monkeypatch.setattr("rich_senpai.tools.file_access._guard.config.WORKDIR", tmp_path)
        outside = Path(tempfile.gettempdir()) / "no_replace.txt"
        result = replace_in_file(str(outside), "old", "new")
        assert not result.ok
        assert "outside the workdir" in result.text

    def test_allow_outside_workdir_bypasses(self, monkeypatch, tmp_path):
        monkeypatch.setattr("rich_senpai.tools.file_access._guard.config.WORKDIR", tmp_path)
        outside = Path(tempfile.gettempdir()) / "yes_replace.txt"
        try:
            outside.write_text("old")
            result = replace_in_file(
                str(outside), "old", "new", allow_outside_workdir=True
            )
            assert result.ok
        finally:
            outside.unlink(missing_ok=True)
