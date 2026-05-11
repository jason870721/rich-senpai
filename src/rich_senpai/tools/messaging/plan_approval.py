# plan_approval — approve or reject a teammate's plan.
from rich_senpai.core import state
from rich_senpai.core.unit.team.messaging import plan_requests
from rich_senpai.tools.tool_result import ToolResult


SPEC = {
    "name": "plan_approval",
    "description": (
        "Approve or reject a teammate's outstanding plan request. "
        "request_id must match a pending entry recorded when the "
        "teammate sent its plan_approval_request."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "request_id": {"type": "string"},
            "approve": {"type": "boolean"},
            "feedback": {"type": "string"},
        },
        "required": ["request_id", "approve"],
    },
}


def plan_approval(request_id: str, approve: bool, feedback: str = "") -> ToolResult:
    req = plan_requests.get(request_id)
    if not req:
        return ToolResult(
            text=f"error: unknown plan request_id '{request_id}'",
            ok=False,
        )
    req["status"] = "approved" if approve else "rejected"
    state.BUS.send(
        state.LEAD_NAME,
        req["from"],
        feedback,
        msg_type="plan_approval_response",
        extra={
            "request_id": request_id,
            "approve": approve,
            "feedback": feedback,
        },
    )
    return ToolResult(text=f"Plan {req['status']} for '{req['from']}'")
