# wait tool — synthetic terminal signal intercepted by the agent core.
#
# Registered in TOOL_SPECS so the model can emit it like any other tool_use
# block. The agent core checks for this name *before* dispatch and exits the
# cycle cleanly with stop_reason="wait". The handler below should never run
# in normal operation.

SPEC = {
    "name": "wait",
    "description": (
        "Terminal signal for this cycle. Call this with no arguments when "
        "you are done analyzing and acting for now and want the runner to "
        "sleep until the next scheduled tick. Do not call any other tool in "
        "the same turn as wait."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
    },
}


def wait() -> str:
    return (
        "error: wait must be intercepted by the agent core; reaching this "
        "handler means the loop is misconfigured."
    )
