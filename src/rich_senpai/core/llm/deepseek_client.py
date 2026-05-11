"""Deepseek implementation of LLMClient (async).
"""

from __future__ import annotations

from typing import Any

import anthropic

from rich_senpai.core.config import MODEL_ID
from rich_senpai.core.llm.base import (
    ContentBlock,
    LLMClient,
    LLMResponse,
    Message,
    TextBlock,
    ThinkingBlock,
    RedactedThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
)


class DeepseekLLMClient(LLMClient):
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
    if isinstance(block, ThinkingBlock):
        return {
            "type": "thinking",
            "thinking": block.thinking,
            "signature": block.signature,
        }
    if isinstance(block, RedactedThinkingBlock):
        return {
            "type": "redacted_thinking",
            "data": block.data,
        }
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
        elif b.type == "thinking":
            blocks.append(
                ThinkingBlock(
                    thinking=b.thinking,
                    signature=b.signature,
                )
            )
        elif b.type == "redacted_thinking":
            blocks.append(
                RedactedThinkingBlock(data=b.data)
            )
        elif b.type == "tool_use":
            blocks.append(
                ToolUseBlock(
                    id=b.id,
                    name=b.name,
                    input=dict(b.input) if b.input else {},
                )
            )
    return LLMResponse(
        content=blocks,
        stop_reason=resp.stop_reason or "end_turn",
        usage=Usage(
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
        ),
    )