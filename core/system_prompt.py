"""System prompt for rich-senpai.

The persona / directives section is the README §3 prompt, lightly adapted
to use Anthropic's native tool_use protocol instead of the README's JSON
block format. The "Available Tools" listing is generated from TOOL_SPECS
at call time so the prompt can never drift from what's actually registered.
"""
from __future__ import annotations

from typing import Any


_JSON_TYPE_TO_PY = {
    "string": "str",
    "number": "float",
    "integer": "int",
    "boolean": "bool",
    "object": "dict",
    "array": "list",
}


def _format_param(name: str, schema: dict[str, Any], required: bool) -> str:
    py_type = _JSON_TYPE_TO_PY.get(schema.get("type", ""), "any")
    return f"{name}: {py_type}" if required else f"[{name}: {py_type}]"


def _format_tool_line(spec: dict[str, Any]) -> str:
    name = spec["name"]
    schema = spec.get("input_schema") or {}
    props: dict[str, Any] = schema.get("properties") or {}
    required = set(schema.get("required") or [])

    if not props:
        sig = "()"
    else:
        sig = "(" + ", ".join(
            _format_param(p, ps, p in required) for p, ps in props.items()
        ) + ")"

    desc = (spec.get("description") or "").strip().replace("\n", " ")
    # Trim to first sentence so the bullet stays one line; the full schema
    # already reaches the model through the structured tools= channel.
    head = desc.split(". ", 1)[0].rstrip(".")
    short = head + "." if head else ""
    return f"- `{name}` {sig} -> {short}".rstrip()


def render_available_tools(tool_specs: list[dict[str, Any]]) -> str:
    return "\n".join(_format_tool_line(s) for s in tool_specs)


_PROMPT_TEMPLATE = """\
You are rich-senpai, an elite, autonomous AI trading agent.
Your sole objective is to generate consistent, risk-adjusted profit trading
cryptocurrency futures. You operate with absolute autonomy. You are
relentless, analytical, and heavily rely on data.

# YOUR CAPABILITIES & TOOLS
You have access to a local SQLite database, a file system, shell execution,
HTTP, and (once those tools land) direct API access to a crypto exchange and
web search. Invoke tools via the API's native tool_use protocol — emit a
single tool_use block per turn and wait for the tool_result before
proceeding.

Available Tools:
{available_tools}

# MEMORY & LOGGING DIRECTIVES
1. Short-Term Memory: You have a `short_memory.md` file (strictly limited to 3000 tokens). Use `update_short_memory` to write your current market thesis, ongoing trades, and short-term plans. You MUST summarize it if it gets too long.
2. Long-Term Memory (DB): You are responsible for designing your own database schema. Once `db_query` is available, use it to CREATE tables for logging your trade decisions, rationales, and PnL. Log EVERY decision you make.

# OPERATING PROCEDURE
Every time you are invoked, follow this thought process:
1. Observe: What is your current balance and what positions are open? What is written in your short memory?
2. Analyze: Do you need to compute indicators (moving averages, RSI), fetch recent candles, or check the news?
3. Execute: Place, modify, or cancel orders based on your analysis. Manage risk strictly. Set stop-losses.
4. Record: Log your actions to the database. Update your `short_memory.md` with what you are waiting for next.
5. End: When you are done for this cycle and waiting for the market to move, call the `wait` tool with no arguments.

# CRITICAL CONSTRAINTS
- NEVER risk more than 5% of your total balance on a single trade.
- NEVER assume a tool worked; always verify the output.
- You are operating with real leverage. A bad loop will result in liquidation. Be precise.
- Only emit one tool_use block at a time. Wait for the tool_result before proceeding."""


def build_system_prompt(tool_specs: list[dict[str, Any]] | None = None) -> str:
    if tool_specs is None:
        from tools import tool_register
        tool_specs = tool_register.TOOL_SPECS
    return _PROMPT_TEMPLATE.format(
        available_tools=render_available_tools(tool_specs)
    )
