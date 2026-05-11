"""LLM client abstraction. Concrete providers live next to base.py.

`build_default_client()` reads `core.config.LLM_PROVIDER` and constructs
the matching adapter. Callers that don't care which provider they're
talking to should use this instead of importing the concrete classes
directly.
"""
from __future__ import annotations

from rich_senpai.core.llm.anthropic_client import AnthropicLLMClient
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
from rich_senpai.core.llm.ollama_client import OllamaLLMClient

__all__ = [
    "AnthropicLLMClient",
    "ContentBlock",
    "LLMClient",
    "LLMResponse",
    "Message",
    "OllamaLLMClient",
    "TextBlock",
    "ToolResultBlock",
    "ToolUseBlock",
    "Usage",
    "build_default_client",
]


def build_default_client() -> LLMClient:
    """Construct an LLMClient based on `core.config.LLM_PROVIDER`."""
    from rich_senpai.core import config

    provider = config.LLM_PROVIDER
    if provider == "anthropic":
        return AnthropicLLMClient()
    if provider == "ollama":
        return OllamaLLMClient()
    raise ValueError(
        f"Unknown LLM_PROVIDER '{provider}'. "
        f"Valid values: anthropic, ollama."
    )
