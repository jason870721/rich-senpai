"""Project-wide logging configuration.

Reads from the environment (loaded by `python-dotenv` in main.py) and
configures the `rich_senpai` logger hierarchy. Every project module
that wants to log obtains a child logger via ``get_logger(__name__)``
so the level, handlers, and formatting set up here are inherited
automatically.

Why a custom root: this is a TUI app — writing to stderr would scramble
the screen. The default sink is therefore a per-session file under
``$WORKDIR/.senpai/logs/session-<timestamp>.log`` and console output is
opt-in via ``LOG_TO_CONSOLE=1``.

Env vars (read once at ``setup_logging()`` time):

  LOG_LEVEL              DEBUG | INFO | WARNING | ERROR  (default INFO)
  LOG_DIR                Directory for session log files. Defaults to
                          ``$WORKDIR/.senpai/logs``.
  LOG_FILE               Explicit log file path. Overrides LOG_DIR when set.
  LOG_TO_CONSOLE         '1'/'true' to also stream to stderr. Off by
                          default because the TUI owns the terminal.
  LOG_FULL_PAYLOADS      '1'/'true' to disable payload truncation in
                          ``clip()``. Off by default — verbose tool
                          outputs would otherwise dominate the log.
  LOG_MAX_PAYLOAD_CHARS  Per-payload truncation limit. Default 4000.

Usage::

    from core.logging_setup import get_logger, clip
    log = get_logger(__name__)
    log.debug("tool_use name=%s input=%s", name, clip(tool_input))
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from core import config


ROOT_LOGGER_NAME = "rich_senpai"
_DEFAULT_LEVEL = "INFO"
_DEFAULT_MAX_PAYLOAD = 4000
_TRUNCATION_MARKER = "... <truncated {n} more chars>"


_setup_done = False
_log_path: Path | None = None
_truncate_at: int = _DEFAULT_MAX_PAYLOAD
_full_payloads: bool = False


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _resolve_log_path() -> Path:
    explicit = os.environ.get("LOG_FILE", "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    log_dir_env = os.environ.get("LOG_DIR", "").strip()
    log_dir = Path(log_dir_env).expanduser() if log_dir_env else (config.SENPAI_HOME / "logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return log_dir / f"session-{stamp}.log"


def setup_logging() -> Path:
    """Configure the project logger. Idempotent — safe to call once.

    Returns the path the FileHandler is writing to so the caller can
    surface it to the user (TUI banner, startup print, etc.).
    """
    global _setup_done, _log_path, _truncate_at, _full_payloads
    if _setup_done and _log_path is not None:
        return _log_path

    level_name = (os.environ.get("LOG_LEVEL") or _DEFAULT_LEVEL).upper()
    level = getattr(logging, level_name, logging.INFO)

    _truncate_at = _env_int("LOG_MAX_PAYLOAD_CHARS", _DEFAULT_MAX_PAYLOAD)
    _full_payloads = _env_bool("LOG_FULL_PAYLOADS", False)

    log_path = _resolve_log_path()
    _log_path = log_path

    fmt = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d  %(levelname)-7s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(fmt)

    root = logging.getLogger(ROOT_LOGGER_NAME)
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(file_handler)
    # Prevent escape onto Python's root logger (which by default writes
    # to stderr and would clobber the TUI).
    root.propagate = False

    if _env_bool("LOG_TO_CONSOLE", False):
        console = logging.StreamHandler()
        console.setLevel(level)
        console.setFormatter(fmt)
        root.addHandler(console)

    # Quiet noisy third-party HTTP loggers unless the user explicitly
    # asked for DEBUG everywhere.
    third_party_level = logging.DEBUG if level <= logging.DEBUG else logging.WARNING
    for noisy in ("httpx", "httpcore", "anthropic", "ollama"):
        logging.getLogger(noisy).setLevel(third_party_level)

    root.info(
        "logging started level=%s file=%s full_payloads=%s max_payload=%d",
        level_name,
        log_path,
        _full_payloads,
        _truncate_at,
    )
    _setup_done = True
    return log_path


def get_logger(name: str) -> logging.Logger:
    """Return a child of the project's root logger.

    Names already prefixed with ``rich_senpai`` are returned as-is so a
    caller passing ``__name__`` from a module inside this package
    doesn't get a doubled prefix.
    """
    if name == ROOT_LOGGER_NAME or name.startswith(ROOT_LOGGER_NAME + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")


def clip(value: Any, max_chars: int | None = None) -> str:
    """Render ``value`` as a single-line string and truncate for logs.

    Honors ``LOG_FULL_PAYLOADS`` (no truncation when set). Pass every
    variable-length payload through this helper before logging it —
    raw tool outputs and message dumps can be megabytes and would
    otherwise turn the log file into a write-dominated bottleneck.
    """
    if value is None:
        return "None"
    text = value if isinstance(value, str) else repr(value)
    if _full_payloads:
        return text
    limit = max_chars if max_chars is not None else _truncate_at
    if len(text) <= limit:
        return text
    suffix = _TRUNCATION_MARKER.format(n=len(text) - limit)
    return text[:limit] + suffix


def log_path() -> Path | None:
    """Path of the active log file, or None if setup_logging hasn't run."""
    return _log_path
