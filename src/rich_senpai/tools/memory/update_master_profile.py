# update_master_profile tool — overwrites .senpai/user_profile.md.
#
# The agent core injects the contents of this file into the system prompt
# at build time so every turn sees the latest profile of the master (user).
# Use this tool whenever you learn anything noteworthy about the master:
# name, age, career, personality, habits, preferred answer style, current
# concerns, project context — anything that will help future-you reply in
# a more personalized, on-target way.
from pathlib import Path

import tiktoken

from rich_senpai.core.config import USER_PROFILE_PATH, USER_PROFILE_TOKEN_BUDGET
from rich_senpai.tools.tool_result import ToolResult


_ENCODER = tiktoken.get_encoding("cl100k_base")


SPEC = {
    "name": "update_master_profile",
    "description": (
        "Overwrite .senpai/user_profile.md with everything you currently "
        "know about the master (the user you are talking to): name, age, "
        "career, personality, habits, preferred answer style, recent "
        "concerns, ongoing projects — anything that will help you reply "
        "more personally and accurately in future turns. The file is "
        "injected verbatim into the system prompt every turn, so keep it "
        "tight — under "
        f"{USER_PROFILE_TOKEN_BUDGET} tokens total. When it grows past "
        "that, summarize older notes before adding new ones. Call this "
        "tool whenever you learn something durable about the master; "
        "skip it for one-off task details."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "markdown_content": {
                "type": "string",
                "description": (
                    "Full markdown content to write. Overwrites the entire "
                    "file — include everything you want to retain, not just "
                    "the new fact. Suggested sections: Identity, Work, "
                    "Personality & Style, Habits, Current Focus, Notes."
                ),
            },
        },
        "required": ["markdown_content"],
    },
}


def update_master_profile(markdown_content: str) -> ToolResult:
    path = Path(USER_PROFILE_PATH)
    token_count = len(_ENCODER.encode(markdown_content))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown_content, encoding="utf-8")
    except OSError as exc:
        return ToolResult(
            text=f"error: could not write user profile to {path}: {exc}",
            ok=False,
        )
    msg = f"wrote {len(markdown_content)} chars (~{token_count} tokens) to {path}"
    if token_count > USER_PROFILE_TOKEN_BUDGET:
        msg += (
            f" — OVER {USER_PROFILE_TOKEN_BUDGET}-token budget; "
            "summarize older notes on the next update."
        )
    return ToolResult(text=msg)
