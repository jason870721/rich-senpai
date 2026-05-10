"""Anthropic implementation of LLMClient (async).

Uses `anthropic.AsyncAnthropic`, whose underlying httpx connection is
cancelled when the awaiting asyncio task is cancelled — that's how
mid-generation interrupts actually abort the HTTP request rather than
waiting for the model to finish.
"""
from __future__ import annotations

from typing import Any

import anthropic

from core.config import MODEL_ID
from core.llm.base import (
    ContentBlock,
    LLMClient,
    LLMResponse,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
)


class AnthropicLLMClient(LLMClient):
    def __init__(
        self,
        *,
        model: str = MODEL_ID,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        self.model = model
        self._client = client or anthropic.AsyncAnthropic()

    async def create_message(
        self,
        *,
        messages: list[Message],
        system: str,
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> LLMResponse:
        api_messages = [_message_to_api(m) for m in messages]
        resp = await self._client.messages.create(
            model=self.model,
            system=system,
            tools=tools,
            messages=api_messages,
            max_tokens=max_tokens,
        )
        return _response_from_api(resp)


def _message_to_api(message: Message) -> dict[str, Any]:
    return {
        "role": message.role,
        "content": [_block_to_api(b) for b in message.content],
    }


def _block_to_api(block: ContentBlock) -> dict[str, Any]:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    if isinstance(block, ToolUseBlock):
        return {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": block.input,
        }
    if isinstance(block, ToolResultBlock):
        return {
            "type": "tool_result",
            "tool_use_id": block.tool_use_id,
            "content": block.content,
        }
    raise TypeError(f"unknown content block type: {type(block).__name__}")


def _response_from_api(resp: Any) -> LLMResponse:
    blocks: list[ContentBlock] = []
    for b in resp.content:
        if b.type == "text":
            blocks.append(TextBlock(text=b.text))
        elif b.type == "tool_use":
            blocks.append(
                ToolUseBlock(
                    id=b.id,
                    name=b.name,
                    input=dict(b.input) if b.input else {},
                )
            )
        # silently skip block types we don't model yet (e.g. thinking)
    return LLMResponse(
        content=blocks,
        stop_reason=resp.stop_reason or "end_turn",
        usage=Usage(
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
        ),
    )
