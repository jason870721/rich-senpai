# spawn_teammate — start a persistent autonomous teammate.
#
# Async because TeammateManager.spawn() schedules the teammate's ReAct
# loop as an asyncio.Task on the running event loop — that requires the
# handler itself to execute on the loop, not in a worker thread.
from rich_senpai.core import state
from rich_senpai.tools.tool_result import ToolResult


SPEC = {
    "name": "spawn_teammate",
    "description": (
        "Spawn a persistent autonomous teammate that runs its own ReAct "
        "loop as an asyncio task, communicates via the message bus, "
        "and auto-claims unclaimed tasks while idle."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "role": {"type": "string"},
            "prompt": {
                "type": "string",
                "description": "Initial brief for the teammate.",
            },
        },
        "required": ["name", "role", "prompt"],
    },
}


async def spawn_teammate(name: str, role: str, prompt: str) -> ToolResult:
    text = state.get_team().spawn(name, role, prompt)
    # team.spawn returns "error: ..." for already-busy / no-loop cases.
    return ToolResult(text=text, ok=not text.startswith("error"))
