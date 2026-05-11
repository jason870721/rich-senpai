"""Tests for the bash tool — exit codes, output formatting, timeout, cwd."""

import os
import tempfile
from pathlib import Path

from rich_senpai.tools.shell.bash import bash


# ── exit codes & ok flag ─────────────────────────────────────────────────


def test_exit_zero_is_ok():
    result = bash("true")
    assert result.ok
    assert result.text == "exit_code: 0"


def test_nonzero_exit_is_not_ok():
    result = bash("false")
    assert not result.ok
    assert result.text == "exit_code: 1"


def test_explicit_exit_code_propagates():
    result = bash("exit 42")
    assert not result.ok
    assert "exit_code: 42" in result.text


# ── output formatting ────────────────────────────────────────────────────


def test_stdout_only():
    result = bash("echo hello")
    assert result.ok
    assert result.text == "exit_code: 0\nhello"


def test_stderr_only():
    result = bash("echo oops 1>&2")
    assert result.ok  # echo itself succeeds; stderr does not flip ok
    assert "exit_code: 0" in result.text
    assert "oops" in result.text


def test_both_stdout_and_stderr_present():
    result = bash("echo out; echo err 1>&2")
    assert result.ok
    lines = result.text.split("\n")
    assert lines[0] == "exit_code: 0"
    assert "out" in result.text
    assert "err" in result.text


def test_trailing_whitespace_stripped():
    """stdout/stderr are .rstrip()ed before being appended."""
    result = bash("printf 'hello\\n\\n\\n'")
    assert result.ok
    # Should end at the content, not the extra newlines
    assert result.text == "exit_code: 0\nhello"


def test_no_output_just_exit_code():
    result = bash(":")  # bash no-op
    assert result.ok
    assert result.text == "exit_code: 0"


# ── shell features ───────────────────────────────────────────────────────


def test_pipe_chain():
    result = bash("echo 'one two three' | tr ' ' '\\n' | wc -l")
    assert result.ok
    assert "3" in result.text


def test_command_substitution():
    result = bash("echo $(echo nested)")
    assert result.ok
    assert "nested" in result.text


def test_env_var_inherited():
    """Subprocess inherits the parent env, so HOME (or PATH) is visible."""
    os.environ["RICH_SENPAI_TEST_VAR"] = "expected_value"
    try:
        result = bash("echo $RICH_SENPAI_TEST_VAR")
        assert result.ok
        assert "expected_value" in result.text
    finally:
        del os.environ["RICH_SENPAI_TEST_VAR"]


# ── cwd parameter ────────────────────────────────────────────────────────


def test_cwd_changes_working_directory():
    with tempfile.TemporaryDirectory() as tmp:
        result = bash("pwd", cwd=tmp)
        assert result.ok
        # macOS prepends /private to /tmp paths via realpath; tolerate both.
        resolved = str(Path(tmp).resolve())
        assert resolved in result.text or tmp in result.text


def test_cwd_default_is_process_cwd():
    result = bash("pwd")
    assert result.ok
    assert os.getcwd() in result.text


# ── timeout ──────────────────────────────────────────────────────────────


def test_timeout_kills_long_command():
    result = bash("sleep 5", timeout=0.2)
    assert not result.ok
    assert "timed out" in result.text
    assert "0.2" in result.text


def test_timeout_includes_command_in_message():
    result = bash("sleep 5", timeout=0.1)
    assert not result.ok
    assert "sleep 5" in result.text


def test_command_completing_before_timeout_passes():
    result = bash("echo fast", timeout=5.0)
    assert result.ok
    assert "fast" in result.text
