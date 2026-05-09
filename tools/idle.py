# idle tool — placeholder for the lead. Teammates handle this internally.

SPEC = {
    "name": "idle",
    "description": (
        "Signal that there's no more work to do. Only meaningful for "
        "spawned teammates; the lead does not idle."
    ),
    "input_schema": {"type": "object", "properties": {}},
}


def idle() -> str:
    return "Lead does not idle."
