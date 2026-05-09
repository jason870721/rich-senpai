# update_short_memory tool — overwrites short_memory.md with new content.
#
# The agent core injects the contents of this file into the first user
# message of every cycle. The path is read from RICH_SENPAI_SHORT_MEM at
# call time, falling back to the project-root default. The agent core
# reads the same env var in __init__ so both stay in sync.
import os
from pathlib import Path


_DEFAULT_PATH = "short_memory.md"


SPEC = {
    "name": "update_short_memory",
    "description": (
        "Overwrite your short_memory.md scratchpad with new markdown content. "
        "Use this to persist your market thesis, ongoing trades, and "
        "short-term plans across cycles. Keep the total under 3000 tokens; "
        "summarize older notes if needed."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "markdown_content": {
                "type": "string",
                "description": "Full markdown content to write. Overwrites the entire file.",
            },
        },
        "required": ["markdown_content"],
    },
}


def update_short_memory(markdown_content: str) -> str:
    path = Path(os.environ.get("RICH_SENPAI_SHORT_MEM", _DEFAULT_PATH))
    try:
        bytes_written = path.write_text(markdown_content, encoding="utf-8")
    except OSError as exc:
        return f"error: could not write short memory to {path}: {exc}"
    return f"wrote {bytes_written} bytes to {path}"
