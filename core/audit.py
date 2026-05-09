"""SQLite audit log for agent cycles.

Every call to AgentCore.run_cycle writes one row to agent_logs — including
when the cycle dies with an exception. This is the forensic log; the
agent's own tables (created later via db_query) are its working memory.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any


_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_started TIMESTAMP NOT NULL,
    cycle_ended   TIMESTAMP NOT NULL,
    stop_reason   TEXT NOT NULL,
    iterations    INTEGER NOT NULL,
    user_input    TEXT,
    raw_messages  TEXT,
    tool_calls    TEXT,
    usage_in      INTEGER,
    usage_out     INTEGER
);
"""


def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None)  # autocommit
    conn.execute(_SCHEMA)
    return conn


def _serialize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Make a JSON-safe copy of the message list. Anthropic content blocks
    are pydantic-ish objects with .model_dump(); tool_result dicts pass
    through unchanged; bare strings (initial user msg) pass through too."""
    out: list[dict[str, Any]] = []
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            out.append({"role": m["role"], "content": content})
        elif isinstance(content, list):
            blocks: list[Any] = []
            for block in content:
                if hasattr(block, "model_dump"):
                    blocks.append(block.model_dump())
                elif isinstance(block, dict):
                    blocks.append(block)
                else:
                    blocks.append(repr(block))
            out.append({"role": m["role"], "content": blocks})
        else:
            out.append({"role": m["role"], "content": repr(content)})
    return out


def log_cycle(
    conn: sqlite3.Connection,
    *,
    result,
    messages: list[dict[str, Any]],
    user_input: str,
    started: datetime,
    ended: datetime,
    error_text: str | None = None,
) -> int:
    raw = json.dumps(
        {"messages": _serialize_messages(messages), "error": error_text},
        default=str,
    )
    tool_calls_json = json.dumps(
        [
            {"name": tc.name, "input": tc.input, "output": tc.output}
            for tc in result.tool_calls
        ],
        default=str,
    )
    cur = conn.execute(
        """
        INSERT INTO agent_logs
          (cycle_started, cycle_ended, stop_reason, iterations,
           market_state, raw_messages, tool_calls, usage_in, usage_out)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            started.isoformat(),
            ended.isoformat(),
            result.stop_reason,
            result.iterations,
            user_input,
            raw,
            tool_calls_json,
            result.usage.get("input_tokens", 0),
            result.usage.get("output_tokens", 0),
        ),
    )
    return cur.lastrowid or 0
