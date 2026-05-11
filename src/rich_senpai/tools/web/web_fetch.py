# web_fetch tool — download a URL and return readable text.
#
# `mode="readable"` (default) runs trafilatura's extractor to strip nav, ads,
# and scripts, returning the article body. `mode="raw"` skips extraction and
# returns the response text. Binary / image / PDF content-types are refused
# up-front so we never dump bytes into the chat.
from __future__ import annotations

import time
from urllib.parse import urlparse

from rich_senpai.core.config import (
    WEB_FETCH_MAX_CHARS,
    WEB_FETCH_TIMEOUT,
    WEB_USER_AGENT,
)
from rich_senpai.core.logging_setup import get_logger
from rich_senpai.tools.tool_result import ToolResult


log = get_logger(__name__)

_HARD_CHAR_CAP = 200_000
_READABLE_MIN_LEN = 200

_ALLOWED_TEXT_TYPES = (
    "text/",
    "application/json",
    "application/xml",
    "application/xhtml",
    "application/rss",
    "application/atom",
    "application/javascript",
    "application/ld+json",
)


SPEC = {
    "name": "web_fetch",
    "description": (
        "Download a single http(s) URL and return its main readable "
        "content (boilerplate stripped via trafilatura). Pass mode='raw' "
        "to get the unparsed response text instead. Truncates to "
        f"~{WEB_FETCH_MAX_CHARS} chars by default. Refuses binary / image "
        "/ PDF content-types. Pair with `web_search` to discover URLs."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Absolute http:// or https:// URL.",
            },
            "max_chars": {
                "type": "integer",
                "description": (
                    f"Truncation cap on the returned body (default "
                    f"{WEB_FETCH_MAX_CHARS}, hard cap {_HARD_CHAR_CAP})."
                ),
            },
            "mode": {
                "type": "string",
                "enum": ["readable", "raw"],
                "description": (
                    "'readable' (default) extracts article text via "
                    "trafilatura; 'raw' returns response.text unparsed."
                ),
            },
        },
        "required": ["url"],
    },
}


def web_fetch(
    url: str,
    max_chars: int = WEB_FETCH_MAX_CHARS,
    mode: str = "readable",
) -> ToolResult:
    if not url or not isinstance(url, str):
        return ToolResult(text="error: 'url' is required.", ok=False)
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return ToolResult(
            text=f"error: refusing non-http(s) scheme: {parsed.scheme!r}",
            ok=False,
        )
    if mode not in ("readable", "raw"):
        return ToolResult(
            text=f"error: invalid mode {mode!r} (expected 'readable' or 'raw').",
            ok=False,
        )
    cap = max(500, min(int(max_chars or WEB_FETCH_MAX_CHARS), _HARD_CHAR_CAP))

    try:
        import requests
    except ImportError:
        return ToolResult(
            text="error: 'requests' package not installed.", ok=False,
        )

    started = time.monotonic()
    try:
        resp = requests.get(
            url,
            timeout=WEB_FETCH_TIMEOUT,
            headers={"User-Agent": WEB_USER_AGENT},
            allow_redirects=True,
        )
    except requests.exceptions.Timeout:
        return ToolResult(
            text=f"error: web_fetch timed out after {WEB_FETCH_TIMEOUT}s: {url}",
            ok=False,
        )
    except requests.exceptions.ConnectionError as exc:
        return ToolResult(
            text=f"error: could not reach {url}: {exc}", ok=False,
        )
    except requests.exceptions.RequestException as exc:
        return ToolResult(
            text=f"error: web_fetch failed for {url}: {exc}", ok=False,
        )
    elapsed_ms = (time.monotonic() - started) * 1000

    ctype = (resp.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
    if ctype and not any(ctype.startswith(prefix) for prefix in _ALLOWED_TEXT_TYPES):
        return ToolResult(
            text=(
                f"error: refusing non-text content-type {ctype!r} for {url}. "
                "Use `bash` with curl + a saver if you really need the bytes."
            ),
            ok=False,
        )

    ok = 200 <= resp.status_code < 400
    log.debug(
        "web_fetch url=%s status=%d ok=%s ctype=%s elapsed_ms=%.0f",
        url, resp.status_code, ok, ctype, elapsed_ms,
    )

    body = _extract_body(resp, mode=mode, ctype=ctype)
    full_len = len(body)
    if full_len > cap:
        body = body[:cap] + (
            f"\n\n[... truncated, {full_len - cap} more chars; "
            f"re-call web_fetch with mode='raw' and a larger max_chars to get more]"
        )

    header = (
        f"[Fetched: {url} — HTTP {resp.status_code}, "
        f"{full_len} chars, {elapsed_ms:.0f} ms, mode={mode}]"
    )
    if not ok:
        return ToolResult(text=f"{header}\n{body}", ok=False)
    return ToolResult(text=f"{header}\n{body}", ok=True)


def _extract_body(resp, *, mode: str, ctype: str) -> str:
    """Apply the requested extraction mode and return the body string."""
    if mode == "raw":
        return resp.text

    # JSON / plain text / XML — skip trafilatura, return body as-is.
    if ctype and not ctype.startswith("text/html") and not ctype.startswith(
        "application/xhtml"
    ):
        return resp.text

    try:
        import trafilatura
    except ImportError:
        return (
            "[trafilatura not installed; returning raw response text]\n"
            + resp.text
        )

    extracted = trafilatura.extract(
        resp.text,
        include_links=True,
        include_formatting=True,
        favor_recall=True,
    )
    if not extracted or len(extracted) < _READABLE_MIN_LEN:
        return (
            "[no article content extracted; raw HTML follows]\n"
            + resp.text
        )
    return extracted
