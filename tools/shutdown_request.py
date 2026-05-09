# shutdown_request — ask a teammate to stop cleanly.
from core import state
from core.messaging import new_request_id, shutdown_requests


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


def shutdown_request(teammate: str) -> str:
    req_id = new_request_id()
    shutdown_requests[req_id] = {"target": teammate, "status": "pending"}
    state.BUS.send(
        state.LEAD_NAME,
        teammate,
        "Please shut down.",
        msg_type="shutdown_request",
        extra={"request_id": req_id},
    )
    return f"Shutdown request {req_id} sent to '{teammate}'"
