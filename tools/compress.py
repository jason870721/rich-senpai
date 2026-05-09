# compress tool — sentinel for manual auto-compaction.
#
# Like `wait`, this is intercepted by the agent core. The agent core
# notices the tool_use, runs core.compaction.auto_compact on the
# message list, and returns to the caller. The handler below should
# never run in normal operation.

SPEC = {
    "name": "compress",
    "description": (
        "Manually compress the conversation context. Use this when the "
        "transcript has grown large but you do not want to wait for the "
        "automatic threshold. Takes no arguments."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
    },
}


def compress() -> str:
    return (
        "error: compress must be intercepted by the agent core; reaching "
        "this handler means the loop is misconfigured."
    )
