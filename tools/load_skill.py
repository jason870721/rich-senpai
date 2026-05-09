# load_skill tool — return the markdown body of a registered skill.
from core import state


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


def load_skill(name: str) -> str:
    return state.SKILLS.load(name)
