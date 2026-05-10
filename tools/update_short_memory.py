# update_short_memory tool — overwrites short_memory.md with new content.
#
# The agent core injects the contents of this file into the first user
# message of every cycle. The path is read from RICH_SENPAI_SHORT_MEM at
# call time, falling back to the project-root default. The agent core
# reads the same env var in __init__ so both stay in sync.
from pathlib import Path

from core.config import SHORT_MEMORY_PATH
from tools.tool_result import ToolResult


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


def update_short_memory(markdown_content: str) -> ToolResult:
    path = Path(SHORT_MEMORY_PATH)
    try:
        bytes_written = path.write_text(markdown_content, encoding="utf-8")
    except OSError as exc:
        return ToolResult(
            text=f"error: could not write short memory to {path}: {exc}",
            ok=False,
        )
    return ToolResult(text=f"wrote {bytes_written} bytes to {path}")
