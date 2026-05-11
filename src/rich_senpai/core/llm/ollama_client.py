"""Ollama implementation of LLMClient (async).

Talks to a local (or remote) Ollama server via the official `ollama`
Python SDK's `AsyncClient`. Translates between our provider-neutral
Message/ContentBlock shapes and the OpenAI-style chat protocol Ollama
exposes.

Cancelling the awaiting task cancels the underlying httpx request so
mid-generation interrupts abort the HTTP call.

Tool calling notes:
  * `tools` are JSON-Schema specs in the same shape Anthropic uses
    (`name`, `description`, `input_schema`). We rewrap them as
    `{"type": "function", "function": {"name", "description",
    "parameters"}}` for Ollama.
  * Ollama responses don't always carry a tool-call `id`. When one is
    missing we synthesize a `tu_<hex>` id; subsequent ToolResultBlocks
    reference that synthetic id, so round-trips stay consistent.
  * Round-trip ordering: a user turn that mixes ToolResultBlocks with a
    plain TextBlock becomes one `tool` message per tool result followed
    by an optional `user` message. This matches the OpenAI convention
    where every tool result must directly follow the assistant turn
    that emitted the matching tool_call.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

import ollama

from rich_senpai.core import config
from rich_senpai.core.llm.base import (
    ContentBlock,
    LLMClient,
    LLMResponse,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
)


class OllamaLLMClient(LLMClient):
    def __init__(
        self,
        *,
        model: str | None = None,
        host: str | None = None,
        client: ollama.AsyncClient | None = None,
    ) -> None:
        self.model = model or config.MODEL_ID
        self._client = client or ollama.AsyncClient(host=host or config.OLLAMA_HOST)

    async def create_message(
        self,
        *,
        messages: list[Message],
        system: str,
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> LLMResponse:
        ollama_messages = self._messages_to_api(messages, system)
        ollama_tools = [_tool_spec_to_api(t) for t in tools] if tools else None
        resp = await self._client.chat(
            model=self.model,
            messages=ollama_messages,
            tools=ollama_tools,
            options={"num_predict": max_tokens},
        )
        return _response_from_api(resp)

    # ----- translation helpers ----------------------------------------

    @staticmethod
    def _messages_to_api(
        messages: list[Message],
        system: str,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if system:
            out.append({"role": "system", "content": system})
        for m in messages:
            out.extend(_message_to_api(m))
        return out


def _tool_spec_to_api(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": spec["name"],
            "description": spec.get("description", ""),
            "parameters": spec.get("input_schema") or {
                "type": "object",
                "properties": {},
            },
        },
    }


def _message_to_api(message: Message) -> list[dict[str, Any]]:
    if message.role == "assistant":
        return [_assistant_to_api(message.content)]
    return _user_to_api(message.content)


def _assistant_to_api(blocks: list[ContentBlock]) -> dict[str, Any]:
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for b in blocks:
        if isinstance(b, TextBlock):
            text_parts.append(b.text)
        elif isinstance(b, ToolUseBlock):
            # ollama-python's pydantic model expects `arguments` as a dict,
            # NOT the JSON string OpenAI uses on the wire. Pass the raw
            # input dict; the SDK serializes it.
            tool_calls.append(
                {
                    "id": b.id,
                    "type": "function",
                    "function": {
                        "name": b.name,
                        "arguments": dict(b.input or {}),
                    },
                }
            )
    msg: dict[str, Any] = {"role": "assistant", "content": "\n".join(text_parts)}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg


def _user_to_api(blocks: list[ContentBlock]) -> list[dict[str, Any]]:
    text_parts: list[str] = []
    tool_results: list[tuple[str, str]] = []
    for b in blocks:
        if isinstance(b, TextBlock):
            text_parts.append(b.text)
        elif isinstance(b, ToolResultBlock):
            tool_results.append((b.tool_use_id, str(b.content)))

    out: list[dict[str, Any]] = []
    # Tool-result messages must immediately follow the assistant turn that
    # emitted the matching tool_call, so emit them first.
    for tcid, content in tool_results:
        out.append({"role": "tool", "tool_call_id": tcid, "content": content})
    if text_parts:
        out.append({"role": "user", "content": "\n".join(text_parts)})
    return out


def _response_from_api(resp: Any) -> LLMResponse:
    msg = _attr(resp, "message") or {}
    content_text = _attr(msg, "content") or ""
    raw_tool_calls = _attr(msg, "tool_calls") or []

    blocks: list[ContentBlock] = []
    if content_text:
        blocks.append(TextBlock(text=content_text))
    for tc in raw_tool_calls:
        fn = _attr(tc, "function") or {}
        name = _attr(fn, "name")
        if not name:
            continue
        args = _attr(fn, "arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except json.JSONDecodeError:
                args = {}
        tc_id = _attr(tc, "id") or f"tu_{uuid.uuid4().hex[:12]}"
        blocks.append(
            ToolUseBlock(id=tc_id, name=name, input=dict(args) if args else {})
        )

    if any(isinstance(b, ToolUseBlock) for b in blocks):
        stop_reason = "tool_use"
    else:
        done = _attr(resp, "done_reason") or "stop"
        stop_reason = "max_tokens" if done == "length" else "end_turn"

    return LLMResponse(
        content=blocks,
        stop_reason=stop_reason,
        usage=Usage(
            input_tokens=int(_attr(resp, "prompt_eval_count") or 0),
            output_tokens=int(_attr(resp, "eval_count") or 0),
        ),
    )


def _attr(obj: Any, name: str) -> Any:
    """Read a field from either a dict or a pydantic-style object."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)
