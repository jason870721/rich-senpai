# wait tool — synthetic sleep signal intercepted by the agent core.
#
# Registered in TOOL_SPECS so the model can emit it like any other tool_use
# block. The agent core checks for this name *before* dispatch, sleeps the
# requested duration via a cancellable asyncio.sleep, then continues
# iterating so the next pre-LLM hooks (background drain, inbox drain,
# auto-compact) can pick up anything that arrived while we were idle. The
# handler below should never run in normal operation — reaching it means
# the loop is misconfigured, hence ok=False.

from rich_senpai.core.config import WAIT_DEFAULT_SECONDS, WAIT_MAX_SECONDS
from rich_senpai.tools.tool_result import ToolResult


SPEC = {
    "name": "wait",
    "description": (
        "Sleep, then continue the cycle. Call this when there's nothing "
        "useful to do right now but you're waiting on something — a "
        "background_run to finish, inbox messages to arrive, etc. After "
        "the sleep, the next iteration drains background results / inbox "
        "before calling the model again, so you'll see anything that "
        f"finished while idle. Default {WAIT_DEFAULT_SECONDS}s, max "
        f"{WAIT_MAX_SECONDS}s. Don't combine with other tools in the "
        "same turn. To END the turn instead of sleeping, just respond "
        "with text and no tool calls."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "seconds": {
                "type": "integer",
                "description": (
                    f"How long to sleep. Defaults to {WAIT_DEFAULT_SECONDS}; "
                    f"clamped to [1, {WAIT_MAX_SECONDS}]."
                ),
            },
        },
    },
}


def wait(seconds: int = WAIT_DEFAULT_SECONDS) -> ToolResult:
    return ToolResult(
        text=(
            "error: wait must be intercepted by the agent core; "
            "reaching this handler means the loop is misconfigured."
        ),
        ok=False,
    )
