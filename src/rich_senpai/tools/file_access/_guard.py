"""Path-traversal guard shared by all file-access tools.

Resolves paths relative to WORKDIR and denies access outside it unless
explicitly overridden.
"""

from pathlib import Path

from rich_senpai.core import config


def _is_within(child: Path, parent: Path) -> bool:
    """True if *child* is equal to or nested inside *parent*."""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


class PathOutsideWorkdirError(ValueError):
    """Raised when a resolved path is outside WORKDIR and
    allow_outside_workdir was not set to True."""


def resolve_safe(
    path_str: str,
    *,
    allow_outside_workdir: bool = False,
) -> Path:
    """Resolve *path_str* and verify it's within ``config.WORKDIR``.

    Relative paths are resolved against ``config.WORKDIR``. If the
    resolved path lies outside the workdir and *allow_outside_workdir*
    is ``False``, raises :class:`PathOutsideWorkdirError`.

    Returns the resolved :class:`Path`.
    """
    file_path = Path(path_str).expanduser()
    if not file_path.is_absolute():
        file_path = config.WORKDIR / file_path
    resolved = file_path.resolve()
    if not allow_outside_workdir and not _is_within(resolved, config.WORKDIR):
        raise PathOutsideWorkdirError(
            f"path {path_str!r} resolves to {resolved}, "
            f"which is outside the workdir ({config.WORKDIR}). "
            f"Pass allow_outside_workdir=True to override."
        )
    return resolved
