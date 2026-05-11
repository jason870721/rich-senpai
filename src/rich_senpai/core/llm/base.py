"""Provider-neutral LLM client interface.

Anything in `core` (and beyond) that needs to talk to a language model goes
through `LLMClient.create_message`. Concrete providers (Anthropic, OpenAI,
local, ...) translate between their wire format and the dataclasses defined
here, so swapping providers is a one-line change at the call site.

`create_message` is async — implementations must use the provider's async
client (e.g. `anthropic.AsyncAnthropic`, `ollama.AsyncClient`) so that
cancellation of the awaiting task aborts the in-flight HTTP request, not
just the post-response processing.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Union


@dataclass
class TextBlock:
    text: str
    type: str = "text"


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]
    type: str = "tool_use"


@dataclass
class ToolResultBlock:
    tool_use_id: str
    content: str
    type: str = "tool_result"

@dataclass
class ThinkingBlock:
    thinking: str
    signature: str

@dataclass
class RedactedThinkingBlock:
    data: str

ContentBlock = Union[TextBlock, ToolUseBlock, ToolResultBlock, RedactedThinkingBlock, ThinkingBlock]


@dataclass
class Message:
    role: str  # "user" | "assistant"
    content: list[ContentBlock] = field(default_factory=list)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class LLMResponse:
    """One assistant turn from the model. Content holds Text and/or ToolUse
    blocks; ToolResult never appears here (those live on user turns)."""
    content: list[ContentBlock]
    stop_reason: str
    usage: Usage


class LLMClient(ABC):
    """Minimal async chat-completion interface every provider must implement."""

    @abstractmethod
    async def create_message(
        self,
        *,
        messages: list[Message],
        system: str,
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> LLMResponse:
        """Send a chat-completion request and return one assistant turn.

        `tools` is a list of JSON-schema-style specs (name, description,
        input_schema). Implementations are responsible for translating to
        their provider's tool format. Cancelling the awaiting task must
        abort the in-flight HTTP request.
        """
