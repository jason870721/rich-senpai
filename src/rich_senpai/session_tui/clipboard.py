"""System-clipboard adapter.

Pipes text into the first available platform tool. No GUI dependency —
we shell out to `pbcopy` (macOS), `wl-copy` (Wayland), or `xclip` (X11)
in that priority order.

Returns the tool name on success, or ``None`` if no tool was found / all
candidates failed. Callers can use the name to render a "copied via
pbcopy" confirmation; tests can monkeypatch ``copy_to_clipboard`` to a
stub.
"""
from __future__ import annotations

import shutil
import subprocess


_CANDIDATES: list[list[str]] = [
    ["pbcopy"],
    ["wl-copy"],
    ["xclip", "-selection", "clipboard"],
]


def copy_to_clipboard(text: str, *, timeout: float = 2.0) -> str | None:
    """Try each candidate in order; return the first that exits 0."""
    for argv in _CANDIDATES:
        if shutil.which(argv[0]) is None:
            continue
        try:
            proc = subprocess.run(
                argv,
                input=text,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode == 0:
            return argv[0]
    return None
