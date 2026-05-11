"""Unified-diff helpers shared by edit_file and write_file.

Pure-stdlib parser + applier for hunks of the form:

    @@ -A,B +C,D @@
     context line
    -removed line
    +added line
     context line

Only hunk bodies are required. Optional ``--- a/path`` / ``+++ b/path``
file headers are tolerated so the agent can paste a `git diff` snippet
verbatim without us choking on the preamble.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class DiffError(ValueError):
    """Base for diff-related errors. Subclasses carry a human-readable
    message that the tool layer surfaces verbatim to the agent."""


class DiffParseError(DiffError):
    pass


class DiffApplyError(DiffError):
    pass


@dataclass
class Hunk:
    old_start: int          # 1-indexed line in the original file
    old_len: int
    new_start: int          # 1-indexed line in the patched file
    new_len: int
    lines: list[str]        # body lines: " ctx" | "-old" | "+new"


def parse_hunks(diff: str) -> list[Hunk]:
    """Parse a unified diff into a list of Hunks.

    Tolerates an optional ``---`` / ``+++`` file-header preamble. The
    body of each hunk is read greedily until the next ``@@`` header (or
    EOF); the header's count fields ``,B`` / ``,D`` are *advisory* — if
    they disagree with the body we silently auto-recount, mirroring
    ``git apply --recount`` / ``patch -l``. LLMs frequently miscount by
    one when they author diffs, so being strict here is wrong.

    What we actually validate (in apply_hunks) is that every context
    (' ') and removal ('-') line matches the file byte-for-byte. That is
    the real correctness check — the count field is just a hint.
    """
    if not diff or not diff.strip():
        raise DiffParseError("empty diff")

    raw_lines = diff.splitlines()
    i = 0
    # Skip optional file headers — be lenient.
    while i < len(raw_lines) and (raw_lines[i].startswith("--- ") or raw_lines[i].startswith("+++ ")):
        i += 1

    hunks: list[Hunk] = []
    while i < len(raw_lines):
        header = raw_lines[i]
        if header.strip() == "":
            i += 1
            continue
        if not header.startswith("@@"):
            raise DiffParseError(
                f"expected hunk header '@@ -A,B +C,D @@' at line {i + 1}, got {header!r}"
            )
        m = _HUNK_RE.match(header)
        if not m:
            raise DiffParseError(f"malformed hunk header at line {i + 1}: {header!r}")
        old_start = int(m.group(1))
        new_start = int(m.group(3))
        # Header counts are advisory — recounted from body below.
        i += 1

        body: list[str] = []
        actual_old = 0
        actual_new = 0
        # Read body greedily until the next hunk header or EOF. Body line
        # tags ('  ', '-', '+') decide where the hunk ends, not the
        # header counts — see the docstring above.
        while i < len(raw_lines):
            line = raw_lines[i]
            if line.startswith("@@ "):
                break
            if line == "":
                # Fully-empty line is a context line for "" — treat as " ".
                body.append(" ")
                actual_old += 1
                actual_new += 1
                i += 1
                continue
            tag = line[0]
            if tag == " ":
                body.append(line)
                actual_old += 1
                actual_new += 1
            elif tag == "-":
                body.append(line)
                actual_old += 1
            elif tag == "+":
                body.append(line)
                actual_new += 1
            elif tag == "\\":
                # "\ No newline at end of file" — informational, skip.
                pass
            else:
                raise DiffParseError(
                    f"unexpected line in hunk body at line {i + 1}: {line!r} "
                    f"(must start with ' ', '-', or '+')"
                )
            i += 1

        if actual_old == 0 and actual_new == 0:
            raise DiffParseError(
                f"hunk @@ -{old_start},.. +{new_start},.. @@ has no body lines"
            )
        # Trust the body counts (auto-recount). The apply step is the
        # real correctness check — it verifies content match line-by-line.
        hunks.append(Hunk(old_start, actual_old, new_start, actual_new, body))

    if not hunks:
        raise DiffParseError("no hunks found in diff")
    return hunks


def _split_keep_trailing_nl(text: str) -> tuple[list[str], bool]:
    """Split text into lines without the newline char. Track whether the
    original ended with a newline so we can restore the policy on join."""
    if text == "":
        return [], False
    trailing = text.endswith("\n")
    lines = text.split("\n")
    if trailing:
        lines.pop()  # drop the empty trailer that split() introduces
    return lines, trailing


def _join_with_policy(lines: list[str], trailing_nl: bool) -> str:
    if not lines:
        return "\n" if trailing_nl else ""
    return "\n".join(lines) + ("\n" if trailing_nl else "")


def apply_hunks(original: str, hunks: list[Hunk]) -> str:
    """Apply hunks to ``original``. Hunks reference original-file line
    numbers (1-indexed); we track a running offset across hunks.

    Verifies ' ' (context) and '-' (remove) lines match the file
    byte-for-byte. On mismatch raises DiffApplyError with a message
    pinpointing the divergent line."""
    lines, trailing_nl = _split_keep_trailing_nl(original)
    offset = 0  # net delta applied so far (new_len - old_len summed)

    # Reject overlapping hunks: each hunk's old region must start at or
    # after the previous hunk's old end.
    prev_end = 0
    for h in sorted(hunks, key=lambda x: x.old_start):
        if h.old_start < prev_end:
            raise DiffApplyError(
                f"overlapping hunk at @@ -{h.old_start},{h.old_len} @@ "
                f"(previous hunk ended at line {prev_end})"
            )
        prev_end = h.old_start + h.old_len

    # Apply in declared order, using offset to translate old→current.
    for h in hunks:
        # Re-validate region, using the *current* (offset-adjusted) index.
        # 0-indexed position in the working list:
        zero_idx = h.old_start - 1 + offset
        if h.old_len == 0:
            # Pure insertion — no context to verify, but check the position
            # is reachable.
            if zero_idx < 0 or zero_idx > len(lines):
                raise DiffApplyError(
                    f"hunk @@ -{h.old_start},0 @@ insertion point out of range "
                    f"(file has {len(lines) - offset} lines)"
                )
        # Walk the body, matching ' '/'-' against the file.
        cursor = zero_idx
        replacement: list[str] = []
        for body_line in h.lines:
            tag = body_line[0]
            payload = body_line[1:]
            if tag == " ":
                if cursor >= len(lines):
                    raise DiffApplyError(
                        f"hunk @@ -{h.old_start},{h.old_len} @@ ran past end of file "
                        f"at line {cursor - offset + 1}"
                    )
                if lines[cursor] != payload:
                    raise DiffApplyError(
                        f"context mismatch at line {cursor - offset + 1}: "
                        f"expected {payload!r}, found {lines[cursor]!r}. "
                        f"Re-read the file and rebuild the hunk."
                    )
                replacement.append(payload)
                cursor += 1
            elif tag == "-":
                if cursor >= len(lines):
                    raise DiffApplyError(
                        f"hunk @@ -{h.old_start},{h.old_len} @@ ran past end of file "
                        f"at line {cursor - offset + 1}"
                    )
                if lines[cursor] != payload:
                    raise DiffApplyError(
                        f"removal mismatch at line {cursor - offset + 1}: "
                        f"expected {payload!r}, found {lines[cursor]!r}. "
                        f"Re-read the file and rebuild the hunk."
                    )
                cursor += 1
                # do NOT append — line is dropped
            elif tag == "+":
                replacement.append(payload)
            else:  # pragma: no cover — parse_hunks already filtered these
                raise DiffApplyError(f"invalid body tag {tag!r}")

        # Splice replacement into lines.
        lines[zero_idx:zero_idx + h.old_len] = replacement
        offset += h.new_len - h.old_len

    return _join_with_policy(lines, trailing_nl)


def render_new_file_diff(path: str, content: str) -> str:
    """Synthesize a unified diff for a brand-new file (`/dev/null` → path).

    Used by write_file when creating a file so the TUI can render it in
    git-diff style alongside edit_file's output."""
    lines, trailing_nl = _split_keep_trailing_nl(content)
    n = len(lines)
    header = f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{n} @@\n"
    body = "".join(f"+{line}\n" for line in lines)
    if not trailing_nl and lines:
        body += "\\ No newline at end of file\n"
    return header + body
