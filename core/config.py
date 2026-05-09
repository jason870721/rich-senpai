"""Process-wide config read from the environment.

Every tunable knob in the agent flows through this module so there's a
single place to grep for defaults. Modules import the constants they
need at top-level — `from core.config import MAX_ITERATIONS, …` — and
treat them as resolved-at-import-time. If a value needs to change at
runtime, override it on the consumer (e.g. pass `max_iterations=` into
AgentCore) rather than mutating these constants.

Defaults match the values that lived inline in agent_core / compaction /
team / subagent / the tool layer before this file existed.
"""
from __future__ import annotations

import os
from pathlib import Path


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _str(name: str, default: str) -> str:
    raw = os.environ.get(name)
    return raw if raw not in (None, "") else default


# --- LLM -------------------------------------------------------------------
# Which provider AgentCore wires up by default. "anthropic" uses
# core/llm/anthropic_client.py; "ollama" uses core/llm/ollama_client.py.
LLM_PROVIDER: str = _str("LLM_PROVIDER", "anthropic").lower()

# Model id. Default is an Anthropic Haiku tag; for Ollama set this to a
# local model tag like "qwen3.6:latest" or "qwen2.5:7b".
MODEL_ID: str = _str("MODEL_ID", "claude-haiku-4-5-20251001")

# Ollama server URL — only used when LLM_PROVIDER=ollama.
OLLAMA_HOST: str = _str("OLLAMA_HOST", "http://localhost:11434")

# --- Agent loop ------------------------------------------------------------
MAX_ITERATIONS: int = _int("MAX_ITERATIONS", 35)
MAX_TOKENS_PER_CALL: int = _int("MAX_TOKENS_PER_CALL", 4096)
SHORT_MEMORY_TOKEN_BUDGET: int = _int("SHORT_MEMORY_TOKEN_BUDGET", 3000)
TOKEN_THRESHOLD: int = _int("TOKEN_THRESHOLD", 100_000)
TODO_NAG_AFTER_ROUNDS: int = _int("TODO_NAG_AFTER_ROUNDS", 3)

# --- Subagent (`task` tool) -----------------------------------------------
SUBAGENT_MAX_ITERATIONS: int = _int("SUBAGENT_MAX_ITERATIONS", 30)
SUBAGENT_MAX_TOKENS: int = _int("SUBAGENT_MAX_TOKENS", 8000)

# --- Teammate -------------------------------------------------------------
TEAM_POLL_INTERVAL: int = _int("TEAM_POLL_INTERVAL", 5)
TEAM_IDLE_TIMEOUT: int = _int("TEAM_IDLE_TIMEOUT", 60)
TEAM_MAX_TOKENS: int = _int("TEAM_MAX_TOKENS", 8000)

# --- Tool defaults --------------------------------------------------------
BASH_DEFAULT_TIMEOUT: int = _int("BASH_DEFAULT_TIMEOUT", 30)
HTTP_DEFAULT_TIMEOUT: int = _int("HTTP_DEFAULT_TIMEOUT", 30)
BG_DEFAULT_TIMEOUT: int = _int("BG_DEFAULT_TIMEOUT", 120)
WAIT_DEFAULT_SECONDS: int = _int("WAIT_DEFAULT_SECONDS", 15)
WAIT_MAX_SECONDS: int = _int("WAIT_MAX_SECONDS", 300)

# --- Paths ----------------------------------------------------------------
# Root directory for all runtime artifacts (.tasks/, .team/, .transcripts/,
# skills/). Resolved once, here, so every consumer agrees on a single
# absolute path even if the process later chdirs. Override via
# RICH_SENPAI_WORKDIR; defaults to whichever directory was current when
# this module was first imported.
WORKDIR: Path = Path(_str("RICH_SENPAI_WORKDIR", str(Path.cwd()))).expanduser().resolve()
SENPAI_HOME: Path = WORKDIR / ".senpai"
# Subpaths derived from WORKDIR. These are still snapshot-once, but they're
# all anchored to the same root, so callers that import either WORKDIR or
# any of these will see a consistent view.

SKILLS_DIR: Path = SENPAI_HOME / "skills"
TASKS_DIR: Path = SENPAI_HOME / "tasks"
TEAM_DIR: Path = SENPAI_HOME / "team"
INBOX_DIR: Path = TEAM_DIR / "inbox"
TRANSCRIPT_DIR: Path = SENPAI_HOME / "transcripts"

SHORT_MEMORY_PATH: str = _str("RICH_SENPAI_SHORT_MEM", str(SENPAI_HOME / "short_memory.md"))
