"""LLM client abstraction. Concrete providers live next to base.py.

`build_default_client()` reads `core.config.LLM_PROVIDER` and constructs
the matching adapter. Callers that don't care which provider they're
talking to should use this instead of importing the concrete classes
directly.
"""
from __future__ import annotations

import os

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
from rich_senpai.core.llm.deepseek_client import DeepseekLLMClient
from rich_senpai.core.llm.ollama_client import OllamaLLMClient
from rich_senpai.core.llm.anthropic_client import AnthropicLLMClient

__all__ = [
    "AnthropicLLMClient",
    "DeepseekLLMClient",
    "OllamaLLMClient",
    "ContentBlock",
    "LLMClient",
    "LLMResponse",
    "Message",
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
        # export ANTHROPIC_API_KEY=config.LLM_PROVIDER
        os.environ.setdefault("ANTHROPIC_API_KEY", config.LLM_API_KEY)
        return AnthropicLLMClient()
    if provider == "ollama":
        return OllamaLLMClient()
    if provider == "deepseek":
        # export ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
        # export ANTHROPIC_API_KEY=config.LLM_PROVIDER
        os.environ.setdefault("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic")
        os.environ.setdefault("ANTHROPIC_API_KEY", config.LLM_API_KEY)
        return DeepseekLLMClient()
    raise ValueError(
        f"Unknown LLM_PROVIDER '{provider}'. "
        f"Valid values: anthropic, ollama."
    )
