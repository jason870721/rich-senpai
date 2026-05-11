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
LLM_API_KEY: str = _str("LLM_API_KEY", "")

# Model id. Default is an Anthropic Haiku tag; for Ollama set this to a
# local model tag like "qwen3.6:latest" or "qwen2.5:7b".
MODEL_ID: str = _str("MODEL_ID", "claude-haiku-4-5-20251001")

# Ollama server URL — only used when LLM_PROVIDER=ollama.
OLLAMA_HOST: str = _str("OLLAMA_HOST", "http://localhost:11434")

# --- Agent loop ------------------------------------------------------------
MAX_ITERATIONS: int = _int("MAX_ITERATIONS", 35)
MAX_TOKENS_PER_CALL: int = _int("MAX_TOKENS_PER_CALL", 8000)
TOKEN_THRESHOLD: int = _int("TOKEN_THRESHOLD", 100_000)
TODO_NAG_AFTER_ROUNDS: int = _int("TODO_NAG_AFTER_ROUNDS", 3)

# --- Subagent (`task` tool) -----------------------------------------------
SUBAGENT_MAX_ITERATIONS: int = _int("SUBAGENT_MAX_ITERATIONS", 30)
SUBAGENT_MAX_TOKENS_PER_CALL: int = _int("SUBAGENT_MAX_TOKENS_PER_CALL", 8000)

# --- Teammate -------------------------------------------------------------
TEAM_POLL_INTERVAL: int = _int("TEAM_POLL_INTERVAL", 5)
TEAM_IDLE_TIMEOUT: int = _int("TEAM_IDLE_TIMEOUT", 60)
TEAM_MAX_TOKENS: int = _int("TEAM_MAX_TOKENS", 8000)
# Auto-compact threshold for a teammate's own message list, evaluated at
# the top of each work-phase iteration. Defaults to the lead's threshold
# so a single env override (TOKEN_THRESHOLD) tunes both; set
# TEAM_TOKEN_THRESHOLD to decouple them when teammates run on a
# smaller-context model.
TEAM_TOKEN_THRESHOLD: int = _int("TEAM_TOKEN_THRESHOLD", _int("TOKEN_THRESHOLD", 100_000))

# --- Tool defaults --------------------------------------------------------
BASH_DEFAULT_TIMEOUT: int = _int("BASH_DEFAULT_TIMEOUT", 180)
HTTP_DEFAULT_TIMEOUT: int = _int("HTTP_DEFAULT_TIMEOUT", 30)
BG_DEFAULT_TIMEOUT: int = _int("BG_DEFAULT_TIMEOUT", 360)
WAIT_DEFAULT_SECONDS: int = _int("WAIT_DEFAULT_SECONDS", 15)
WAIT_MAX_SECONDS: int = _int("WAIT_MAX_SECONDS", 300)
# Microcompact keeps this many leading chars from each compacted tool result
# so the LLM can still see file headers, first grep hits, etc.
MICROCOMPACT_KEEP_PREFIX: int = _int("MICROCOMPACT_KEEP_PREFIX", 500)
# Progressive microcompact: how many of the most-recent tool_result-carrying
# user turns stay untouched. Floor of 6 enforced at agent init so
# the six progressive tiers (50/30/20/10/5/1%) all get exercised.
MICROCOMPACT_KEEP_RECENT: int = _int("MICROCOMPACT_KEEP_RECENT", 8)
MICROCOMPACT_MIN_KEEP_RECENT: int = 6
# Microcompact fires every N ReAct iterations (lead, subagent, teammate).
TOOL_COMPACT_AFTER_ROUND: int = _int("TOOL_COMPACT_AFTER_ROUND", 5)
# Soft FIFO cap on the per-loop recovery map — guards against unbounded
# growth on very long sessions. Oldest entries evict first; an evicted
# recovery call returns a clear error.
MICROCOMPACT_RECOVERY_CAP: int = _int("MICROCOMPACT_RECOVERY_CAP", 300)
# Compaction-skip threshold: leave tool_results shorter than this alone, since
# the stub itself would be longer than the original.
MICROCOMPACT_MIN_LEN: int = _int("MICROCOMPACT_MIN_LEN", 200)

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

USER_PROFILE_PATH: str = _str("RICH_SENPAI_USER_PROFILE", str(SENPAI_HOME / "user_profile.md"))
USER_PROFILE_TOKEN_BUDGET: int = _int("USER_PROFILE_TOKEN_BUDGET", 3000)

# --- Web tools ------------------------------------------------------------
# `web_fetch` HTTP request timeout (seconds). Distinct from
# HTTP_DEFAULT_TIMEOUT which is consumed by the shell layer for curl-style
# flows; this knob is exclusive to the web_fetch tool.
WEB_FETCH_TIMEOUT: int = _int("WEB_FETCH_TIMEOUT", 30)
# Default truncation cap for `web_fetch`. The handler also enforces a hard
# 200_000 ceiling so a malicious or buggy override can't blow up context.
WEB_FETCH_MAX_CHARS: int = _int("WEB_FETCH_MAX_CHARS", 20_000)
# Default number of results returned by `web_search` (hard cap 15 in-tool).
WEB_SEARCH_MAX_RESULTS: int = _int("WEB_SEARCH_MAX_RESULTS", 5)
# DDG region code for `web_search`. 'wt-wt' = worldwide. Other examples:
# 'us-en', 'uk-en', 'jp-jp'. Per-call `region` arg overrides this default.
WEB_SEARCH_REGION: str = _str("WEB_SEARCH_REGION", "wt-wt")
WEB_USER_AGENT: str = _str(
    "WEB_USER_AGENT",
    "rich-senpai/0.x (+https://github.com/Johnny1110/rich-senpai)",
)
