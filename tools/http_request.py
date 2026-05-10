# http request tool
import requests

from core.config import HTTP_DEFAULT_TIMEOUT
from tools.tool_result import ToolResult


SPEC = {
    "name": "http_request",
    "description": (
        "Send an HTTP request to a URL and return the response status, "
        "headers, and body as a string. Supports common methods (GET, POST, "
        "PUT, PATCH, DELETE) with optional headers and JSON or text body."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "method": {
                "type": "string",
                "description": "HTTP method, e.g. GET, POST, PUT, PATCH, DELETE.",
            },
            "url": {
                "type": "string",
                "description": "Full URL to request.",
            },
            "headers": {
                "type": "object",
                "description": "Optional request headers as a flat string-to-string mapping.",
            },
            "json_body": {
                "type": "object",
                "description": "Optional JSON-serializable body. Sent as application/json.",
            },
            "text_body": {
                "type": "string",
                "description": "Optional raw text body. Ignored if json_body is provided.",
            },
            "timeout": {
                "type": "number",
                "description": (
                    f"Request timeout in seconds. "
                    f"Defaults to {HTTP_DEFAULT_TIMEOUT} (HTTP_DEFAULT_TIMEOUT)."
                ),
            },
        },
        "required": ["method", "url"],
    },
}


def http_request(
    method: str,
    url: str,
    headers: dict | None = None,
    json_body: dict | None = None,
    text_body: str | None = None,
    timeout: float = HTTP_DEFAULT_TIMEOUT,
) -> ToolResult:
    try:
        response = requests.request(
            method=method.upper(),
            url=url,
            headers=headers,
            json=json_body,
            data=text_body if json_body is None else None,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return ToolResult(text=f"error: request failed: {exc}", ok=False)

    header_lines = "\n".join(f"{k}: {v}" for k, v in response.headers.items())
    text = (
        f"status: {response.status_code}\n"
        f"--- headers ---\n{header_lines}\n"
        f"--- body ---\n{response.text}"
    )
    # 2xx and 3xx are conventional success / redirect; 4xx-5xx surface
    # as failures so the TUI can flag them red while the model still
    # sees the full response.
    return ToolResult(text=text, ok=200 <= response.status_code < 400)
