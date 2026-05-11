# web_search tool — DuckDuckGo search returning a numbered markdown list.
#
# Uses the `ddgs` PyPI package (maintained fork of duckduckgo-search) so no
# API key is required. Imports happen lazily inside the handler so a missing
# dependency is reported as a clean tool error rather than crashing module
# load.
from __future__ import annotations

import time

from rich_senpai.core.config import WEB_SEARCH_MAX_RESULTS, WEB_SEARCH_REGION
from rich_senpai.core.logging_setup import get_logger
from rich_senpai.tools.tool_result import ToolResult


log = get_logger(__name__)

_HARD_CAP = 15


SPEC = {
    "name": "web_search",
    "description": (
        "Search the web via DuckDuckGo and return up to N ranked results as "
        "a numbered markdown list (title, URL, snippet). Use this to "
        "discover URLs; use `web_fetch` to read a specific one. No API key "
        "required. Returns 'error: ...' on rate-limit or network failure."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query.",
            },
            "max_results": {
                "type": "integer",
                "description": (
                    f"How many results to return (default "
                    f"{WEB_SEARCH_MAX_RESULTS}, hard cap {_HARD_CAP})."
                ),
            },
            "region": {
                "type": "string",
                "description": (
                    "DDG region code, e.g. 'us-en', 'wt-wt' (worldwide). "
                    "Optional; defaults to the WEB_SEARCH_REGION env value."
                ),
            },
        },
        "required": ["query"],
    },
}


def web_search(
    query: str,
    max_results: int = WEB_SEARCH_MAX_RESULTS,
    region: str | None = None,
) -> ToolResult:
    q = (query or "").strip()
    if not q:
        return ToolResult(text="error: 'query' is required.", ok=False)
    n = max(1, min(int(max_results or WEB_SEARCH_MAX_RESULTS), _HARD_CAP))
    reg = region or WEB_SEARCH_REGION

    try:
        from ddgs import DDGS
    except ImportError:
        return ToolResult(
            text="error: 'ddgs' package not installed — run `pip install ddgs`.",
            ok=False,
        )

    started = time.monotonic()
    try:
        with DDGS() as ddgs:
            raw = list(ddgs.text(q, region=reg, max_results=n))
    except Exception as exc:  # noqa: BLE001 — ddgs raises various network/rate-limit types
        log.warning("web_search failed query=%r err=%s", q, exc)
        return ToolResult(text=f"error: web_search failed: {exc}", ok=False)
    elapsed_ms = (time.monotonic() - started) * 1000

    if not raw:
        return ToolResult(
            text=f"[web_search: '{q}' — no results]",
            ok=True,
        )

    lines = [f"[web_search: '{q}' — {len(raw)} result(s), {elapsed_ms:.0f} ms]"]
    for i, r in enumerate(raw, 1):
        title = (r.get("title") or "").strip() or "(no title)"
        href = (r.get("href") or r.get("url") or "").strip()
        snippet = (r.get("body") or r.get("snippet") or "").strip()
        lines.append(f"{i}. [{title}]({href})")
        if snippet:
            lines.append(f"   {snippet}")
    return ToolResult(text="\n".join(lines), ok=True)
