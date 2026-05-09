"""System prompt for rich-senpai.

Lives in its own module so the prompt text can be edited without touching
the agent loop. AgentCore imports SYSTEM_PROMPT from here and uses it as
the default for its `system_prompt` parameter.
"""
from __future__ import annotations

from core import config, state


def build_system_prompt() -> str:
    skills = state.SKILLS.skills
    if skills:
        skills_block = "\n".join(
            f"  - {name}: {meta['description']}"
            for name, meta in skills.items()
        )
        skills_section = (
            "Available skills (load via the load_skill tool when relevant):\n"
            f"{skills_block}\n"
        )
    else:
        skills_section = ""

    return (
        "You are rich-senpai, an autonomous trading agent (development build).\n"
        "Use the narrowest tool that fits. Persist your thesis and notes via "
        "update_short_memory between cycles (keep it under 3000 tokens — "
        "summarize when it grows). When you're done with this cycle, call wait."
        f"Your workdir is {config.WORKDIR.as_posix()}, custom skills are in "
        f"{config.SKILLS_DIR.as_posix()}.\n"
        f"{skills_section}"
    )


SYSTEM_PROMPT = build_system_prompt()
