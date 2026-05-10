# idle tool — placeholder for the lead. Teammates handle this internally.
from tools.tool_result import ToolResult


SPEC = {
    "name": "idle",
    "description": (
        "Signal that there's no more work to do. Only meaningful for "
        "spawned teammates; the lead does not idle."
    ),
    "input_schema": {"type": "object", "properties": {}},
}


def idle() -> ToolResult:
    # ok=False because the lead invoking idle is a misuse — teammates
    # handle their own idle path inside the team loop, never via this
    # registered handler.
    return ToolResult(text="Lead does not idle.", ok=False)
