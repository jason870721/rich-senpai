"""Agent unit — the lead ReAct loop, conversation compaction, and system prompt."""
from rich_senpai.core.unit.agent.agent_core import AgentCore, CycleResult, ToolCall
from rich_senpai.core.unit.agent.compaction import (
    TRANSCRIPT_DIR,
    auto_compact,
    estimate_tokens,
    microcompact,
)
from rich_senpai.core.unit.agent.sys_prompt import SYSTEM_PROMPT, build_system_prompt

__all__ = [
    "AgentCore",
    "CycleResult",
    "ToolCall",
    "TRANSCRIPT_DIR",
    "auto_compact",
    "estimate_tokens",
    "microcompact",
    "SYSTEM_PROMPT",
    "build_system_prompt",
]
