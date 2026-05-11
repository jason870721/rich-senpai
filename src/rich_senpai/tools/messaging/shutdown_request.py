# shutdown_request — ask a teammate to stop cleanly.
from rich_senpai.core import state
from rich_senpai.core.unit.team.messaging import new_request_id, shutdown_requests
from rich_senpai.tools.tool_result import ToolResult


SPEC = {
    "name": "shutdown_request",
    "description": (
        "Send a shutdown_request message to a named teammate. The lead "
        "tracks the request id so a future shutdown_response can be "
        "correlated."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"teammate": {"type": "string"}},
        "required": ["teammate"],
    },
}


def shutdown_request(teammate: str) -> ToolResult:
    req_id = new_request_id()
    shutdown_requests[req_id] = {"target": teammate, "status": "pending"}
    state.BUS.send(
        state.LEAD_NAME,
        teammate,
        "Please shut down.",
        msg_type="shutdown_request",
        extra={"request_id": req_id},
    )
    return ToolResult(text=f"Shutdown request {req_id} sent to '{teammate}'")
