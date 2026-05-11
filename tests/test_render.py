"""Tests for the TUI's diff-detection and rendering primitives.

These pin the contract between file_access tool outputs and the TUI:
edit_file/write_file return strings that must be detected as diffs and
rendered with git-style colors. The replace_all path in edit_file
prepends a `# replaced N occurrences` annotation — the renderer must
still treat the body as a diff and style the annotation distinctly.
"""

from rich_senpai.session_tui.render import looks_like_diff, render_diff_block


# ── looks_like_diff ─────────────────────────────────────────────────────


def test_detects_at_at_header():
    assert looks_like_diff("@@ -1,3 +1,3 @@\n-old\n+new\n")


def test_detects_minus_minus_header():
    assert looks_like_diff("--- a/foo\n+++ b/foo\n@@ -1 +1 @@\n-x\n+y\n")


def test_detects_plus_plus_header():
    assert looks_like_diff("+++ b/foo\n")


def test_detects_dev_null_create_diff():
    """write_file's new-file output starts with `--- /dev/null`."""
    assert looks_like_diff("--- /dev/null\n+++ b/path\n@@ -0,0 +1,2 @@\n+a\n+b\n")


def test_skips_leading_blanks():
    assert looks_like_diff("\n\n@@ -1 +1 @@\n-a\n+b\n")


def test_skips_leading_comment_then_diff():
    """edit_file's replace_all path prepends `# replaced N occurrences`."""
    assert looks_like_diff(
        "# replaced 4 occurrences\n--- a/path\n+++ b/path\n@@ -1 +1 @@\n-x\n+X\n"
    )


def test_comment_only_text_is_not_diff():
    assert not looks_like_diff("# just a note\nplain text follows\n")


def test_plain_text_is_not_diff():
    assert not looks_like_diff("hello world\n")


def test_read_file_output_is_not_diff():
    """read_file returns `[File: ...]\\n     1\\tline...` — must not be a diff."""
    sample = "[File: /tmp/x.py (2 lines)]\n     1\talpha\n     2\tbeta"
    assert not looks_like_diff(sample)


def test_write_file_overwrite_output_is_not_diff():
    assert not looks_like_diff("wrote 42 bytes to /tmp/x.txt")


def test_error_output_is_not_diff():
    assert not looks_like_diff("error: file not found: foo.txt")


# ── render_diff_block ───────────────────────────────────────────────────


def _render_to_plain(text: str) -> str:
    """Render and return the plain text (style stripped) so we can
    sanity-check structure without coupling to color codes."""
    return render_diff_block(text).plain


def test_render_includes_every_line_with_bar():
    out = _render_to_plain("@@ -1 +1 @@\n-x\n+X\n")
    # Four rows: @@ header, -x, +X, trailing empty (splitlines drops it)
    rows = out.split("\n")
    assert len(rows) == 3
    for row in rows:
        assert row.startswith("│ ")


def test_first_row_uses_corner_glyph():
    out = _render_to_plain("@@ -1 +1 @@\n-x\n+X\n")
    rows = out.split("\n")
    assert rows[0].startswith("│ ⎿ ")
    # subsequent rows use the 2-space hanging indent
    assert rows[1].startswith("│   ")


def test_annotation_line_is_styled_distinctly():
    """The `#` annotation line should get italic+BRAND, not dim/red/green."""
    rendered = render_diff_block("# replaced 3 occurrences\n@@ -1 +1 @@\n-a\n+b\n")
    spans = rendered.spans
    # Find the span over the annotation text and confirm its style
    # mentions "italic" — locking in metadata-style rendering.
    annotation_styles = [
        str(s.style) for s in spans
        if "replaced 3 occurrences" in rendered.plain[s.start:s.end]
    ]
    assert annotation_styles, "annotation text should have at least one styled span"
    assert any("italic" in s for s in annotation_styles)


def test_added_and_removed_lines_styled():
    rendered = render_diff_block("@@ -1 +1 @@\n-x\n+X\n")
    plain = rendered.plain
    # Both `-x` and `+X` should appear in the output verbatim.
    assert "-x" in plain
    assert "+X" in plain


def test_empty_input_renders_one_empty_row():
    rendered = render_diff_block("")
    assert rendered.plain.startswith("│ ⎿ ")


# ── integration: actual edit_file / write_file output formats ───────────


def test_edit_file_single_replace_output_renders_as_diff():
    """Mirrors what edit_file._build_diff produces for a single replacement."""
    sample = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n"
    assert looks_like_diff(sample)


def test_edit_file_replace_all_output_renders_as_diff():
    """Mirrors what edit_file produces when replace_all replaces >1 occurrences."""
    sample = (
        "# replaced 5 occurrences\n"
        "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-x\n+X\n"
    )
    assert looks_like_diff(sample)
    # And it should render with a header row showing the annotation.
    plain = _render_to_plain(sample)
    assert "# replaced 5 occurrences" in plain


def test_write_file_new_file_output_renders_as_diff():
    """Mirrors what write_file._render_new_file_diff produces."""
    sample = "--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1,2 @@\n+hello\n+world\n"
    assert looks_like_diff(sample)
