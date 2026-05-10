# task tool — spawn a subagent to do isolated exploration or work.
from core import state
from core.subagent import run_subagent
from tools.tool_result import ToolResult


SPEC = {
    "name": "task",
    "description": (
        "Spawn a focused subagent for a single self-contained task. "
        "Use 'Explore' (default) for read-only investigation, "
        "'general-purpose' when the subagent also needs to write/edit files. "
        "Returns the subagent's final summary."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Self-contained brief for the subagent.",
            },
            "agent_type": {
                "type": "string",
                "enum": ["Explore", "general-purpose"],
                "description": "Tool surface for the subagent. Defaults to Explore.",
            },
        },
        "required": ["prompt"],
    },
}


async def task(prompt: str, agent_type: str = "Explore") -> ToolResult:
    return ToolResult(
        text=await run_subagent(prompt, llm=state.get_llm(), agent_type=agent_type),
    )
