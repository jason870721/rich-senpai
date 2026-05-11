"""Tests for tool_register.py — call_tool dispatch.

Covers async dispatch, sync-via-thread, error handling, and
return-value normalization.

call_tool is imported lazily because importing tool_register triggers
the import of all tool modules, which chains through state → team →
agent → sys_prompt → tool_register (circular).
"""
import tempfile
from pathlib import Path

import pytest

from rich_senpai.tools.tool_result import ToolResult


def _call_tool():
    from rich_senpai.tools.tool_register import call_tool as ct
    return ct


# Pre-heat: first import attempt hits the circular-import chain
# (tool_register → state → team → agent → sys_prompt → tool_register)
# and raises ImportError, but it loads enough that subsequent imports succeed.
try:
    _call_tool()
except ImportError:
    pass


class TestUnknownTool:
    async def test_unknown_tool_name_returns_error(self):
        result = await _call_tool()("nonexistent_tool", {"x": 1})
        assert not result.ok
        assert result.text.startswith("error: unknown tool")

    async def test_empty_name_returns_error(self):
        result = await _call_tool()("", {})
        assert not result.ok
        assert result.text.startswith("error: unknown tool")


class TestBadArguments:
    async def test_missing_required_arg(self):
        result = await _call_tool()("read_file", {})
        assert not result.ok
        assert "invalid arguments" in result.text.lower()

    async def test_extra_spurious_args_accepted(self):
        """Extra kwargs are passed through — Python raises TypeError only
        for missing required params, not extra ones."""
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "out.txt"
            result = await _call_tool()("write_file", {
                "path": str(f),
                "content": "hello",
                "allow_outside_workdir": True,
            })
            assert result.ok


class TestSyncDispatch:
    async def test_successful_read(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as tf:
            tf.write("line1\nline2\n")
            fpath = tf.name
        try:
            result = await _call_tool()("read_file", {
                "path": fpath,
                "allow_outside_workdir": True,
            })
            assert result.ok
            assert "line1" in result.text
            assert "line2" in result.text
        finally:
            Path(fpath).unlink()

    async def test_toolresult_passthrough(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as tf:
            tf.write("ok")
            fpath = tf.name
        try:
            result = await _call_tool()("read_file", {
                "path": fpath,
                "allow_outside_workdir": True,
            })
            assert isinstance(result, ToolResult)
            assert result.ok
        finally:
            Path(fpath).unlink()

    async def test_failed_toolresult_passthrough(self):
        result = await _call_tool()("read_file", {
            "path": "/nonexistent/read_file_test_xyz.txt",
            "allow_outside_workdir": True,
        })
        assert isinstance(result, ToolResult)
        assert not result.ok
