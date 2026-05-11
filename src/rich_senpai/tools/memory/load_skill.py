# load_skill tool — return the markdown body of a registered skill.
from rich_senpai.core import state
from rich_senpai.tools.tool_result import ToolResult


SPEC = {
    "name": "load_skill",
    "description": (
        "Load a specialized-knowledge skill by name. The skill's body "
        "is returned as a tool result wrapped in <skill> tags. Skills "
        "are discovered from skills/**/SKILL.md."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Skill name (matches the 'name' frontmatter field).",
            }
        },
        "required": ["name"],
    },
}


def load_skill(name: str) -> ToolResult:
    text = state.SKILLS.load(name)
    # SkillLoader.load returns "error: unknown skill ..." for misses;
    # branch on the registry directly so the ok flag is authoritative.
    return ToolResult(text=text, ok=name in state.SKILLS.skills)
