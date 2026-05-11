"""Tests for _diff.py — Hunk parsing, applying, fuzzy matching, error paths."""

import pytest

from rich_senpai.tools.file_access._diff import (
    DiffApplyError,
    DiffParseError,
    Hunk,
    apply_hunks,
    parse_hunks,
)


# ── parse_hunks ────────────────────────────────────────────────────────


def test_parse_simple_hunk():
    diff = """@@ -1,3 +1,4 @@
 line1
 line2
-removed
+added
 line3
"""
    hunks = parse_hunks(diff)
    assert len(hunks) == 1
    h = hunks[0]
    assert h.old_start == 1
    assert h.new_start == 1
    # Body auto-recounted: 4 context/removal lines = old_len 4 in body,
    # but header says 3. Auto-recount trusts body.
    assert h.old_len == 4  # 4 old lines: 3 context + 1 removal
    assert len(h.lines) == 5
    assert h.lines[2] == "-removed"
    assert h.lines[3] == "+added"


def test_parse_hunk_minimal_no_lengths():
    """When lengths are omitted, defaults to 1."""
    diff = """@@ -5 +5 @@
-x
+y
"""
    hunks = parse_hunks(diff)
    h = hunks[0]
    assert h.old_start == 5
    assert h.new_start == 5


def test_parse_multiple_hunks():
    diff = """@@ -1,3 +1,4 @@
 a
-b
+c
 d
@@ -10,2 +11,2 @@
 x
-y
+z
"""
    hunks = parse_hunks(diff)
    assert len(hunks) == 2
    assert hunks[0].lines[1] == "-b"
    assert hunks[1].lines[1] == "-y"


def test_parse_auto_recount():
    """Header says old_len=10, body has 2 lines → recount to 2."""
    diff = """@@ -1,10 +1,4 @@
 keep
-remove
"""
    hunks = parse_hunks(diff)
    h = hunks[0]
    assert h.old_len == 2
    assert h.new_len == 1


def test_parse_skips_no_newline_marker():
    """`\\ No newline at end of file` is informational and skipped."""
    diff = """@@ -1,2 +1,2 @@
 x
\\ No newline at end of file
"""
    hunks = parse_hunks(diff)
    h = hunks[0]
    # Only ' x' is in the body; the `\\ No newline` line is skipped.
    assert len(h.lines) == 1
    assert h.lines[0] == " x"


def test_parse_pure_insertion():
    diff = """@@ -1,0 +1,3 @@
+line1
+line2
+line3
"""
    hunks = parse_hunks(diff)
    h = hunks[0]
    assert h.old_len == 0
    assert h.new_len == 3


def test_parse_pure_deletion():
    diff = """@@ -1,3 +1,0 @@
-line1
-line2
-line3
"""
    hunks = parse_hunks(diff)
    h = hunks[0]
    assert h.old_len == 3
    assert h.new_len == 0


def test_parse_empty_body_raises():
    diff = """@@ -1,0 +1,0 @@
"""
    with pytest.raises(DiffParseError, match="no body"):
        parse_hunks(diff)


def test_parse_empty_diff_raises():
    with pytest.raises(DiffParseError, match="empty diff"):
        parse_hunks("")


def test_parse_no_hunks_raises():
    with pytest.raises(DiffParseError, match="expected hunk header"):
        parse_hunks("just some text\nno hunk here\n")


def test_parse_malformed_header_raises():
    # Missing the @@ at end or wrong format
    with pytest.raises(DiffParseError):
        parse_hunks("not a hunk @@ -1,1 +1,1\n-x\n+y\n")


def test_parse_bad_body_line_raises():
    diff = """@@ -1,1 +1,1 @@
?invalid
"""
    with pytest.raises(DiffParseError, match="unexpected line"):
        parse_hunks(diff)


def test_parse_skips_file_header_preamble():
    diff = """--- a/foo.py
+++ b/foo.py
@@ -1,1 +1,1 @@
-old
+new
"""
    hunks = parse_hunks(diff)
    assert len(hunks) == 1
    assert hunks[0].lines[0] == "-old"
    assert hunks[0].lines[1] == "+new"


def test_parse_empty_line_in_body_treated_as_context():
    """Fully empty lines are treated as context lines (like ' ')."""
    diff = """@@ -1,2 +1,2 @@
 a

 b
"""
    hunks = parse_hunks(diff)
    h = hunks[0]
    # Empty line becomes " " in body, counts for both old and new.
    assert h.old_len == 3
    assert h.new_len == 3


# ── apply_hunks ────────────────────────────────────────────────────────


def test_apply_simple_change():
    original = "line1\nline2\nline3\n"
    diff = """@@ -2,1 +2,1 @@
-line2
+line2-modified
"""
    hunks = parse_hunks(diff)
    result = apply_hunks(original, hunks)
    assert result == "line1\nline2-modified\nline3\n"


def test_apply_insertion():
    original = "line1\nline3\n"
    diff = """@@ -1,1 +1,2 @@
 line1
+line2
"""
    hunks = parse_hunks(diff)
    result = apply_hunks(original, hunks)
    assert result == "line1\nline2\nline3\n"


def test_apply_deletion():
    original = "line1\nline2\nline3\n"
    diff = """@@ -2,1 +2,0 @@
-line2
"""
    hunks = parse_hunks(diff)
    result = apply_hunks(original, hunks)
    assert result == "line1\nline3\n"


def test_apply_multiple_hunks():
    original = "a\nb\nc\nd\ne\n"
    diff = """@@ -1,1 +1,1 @@
-a
+A
@@ -5,1 +5,1 @@
-e
+E
"""
    hunks = parse_hunks(diff)
    result = apply_hunks(original, hunks)
    assert result == "A\nb\nc\nd\nE\n"


def test_apply_fuzzy_match():
    """When line numbers are slightly off, fuzzy matching (±20 lines) corrects them."""
    original = "line1\nline2\nline3\nline4\nline5\n"
    # Header says @@ -1,1 but the change is actually at line 3.
    diff = """@@ -1,1 +1,1 @@
-line3
+line3-modified
"""
    hunks = parse_hunks(diff)
    result = apply_hunks(original, hunks)
    assert result == "line1\nline2\nline3-modified\nline4\nline5\n"


def test_apply_raises_on_removal_mismatch():
    original = "line1\nline2\nline3\n"
    diff = """@@ -2,1 +2,1 @@
-this_line_does_not_exist
+something
"""
    hunks = parse_hunks(diff)
    with pytest.raises(DiffApplyError):
        apply_hunks(original, hunks)


def test_apply_raises_on_context_mismatch():
    """When context lines don't match, fuzzy can't find anchor → error."""
    original = "line1\nline2\nline3\n"
    diff = """@@ -150,1 +150,1 @@
-xyz
+abc
"""
    hunks = parse_hunks(diff)
    # Anchor "xyz" doesn't match anything, fuzzy window exhausted → error.
    with pytest.raises(DiffApplyError):
        apply_hunks(original, hunks)


def test_apply_insertion_at_end():
    original = "line1\nline2\n"
    diff = """@@ -2,1 +2,2 @@
 line2
+line3
"""
    hunks = parse_hunks(diff)
    result = apply_hunks(original, hunks)
    assert result == "line1\nline2\nline3\n"


def test_apply_trailing_newline_preserved():
    original = "line1\nline2\n"
    diff = """@@ -1,1 +1,1 @@
-line1
+LINE1
"""
    hunks = parse_hunks(diff)
    result = apply_hunks(original, hunks)
    assert result == "LINE1\nline2\n"
    assert result.endswith("\n")


def test_apply_no_trailing_newline_preserved():
    original = "line1\nline2"
    diff = """@@ -1,1 +1,1 @@
-line1
+LINE1
"""
    hunks = parse_hunks(diff)
    result = apply_hunks(original, hunks)
    assert result == "LINE1\nline2"
    assert not result.endswith("\n")


def test_apply_pure_insertion_mid_file():
    original = "line1\nline2\n"
    # Insertion at beginning of file: old_start=1, old_len=0.
    diff = """@@ -1,0 +1,2 @@
+inserted1
+inserted2
"""
    hunks = parse_hunks(diff)
    result = apply_hunks(original, hunks)
    # Insertion at start (offset 0): inserted lines come before line1.
    assert result == "inserted1\ninserted2\nline1\nline2\n"
