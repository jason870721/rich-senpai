"""Skill loader (s_full.py s05 mechanism).

A "skill" is a SKILL.md file under skills/ with optional YAML-ish
frontmatter (name + description) and a markdown body. The agent picks one
up at runtime via the load_skill tool when it needs specialized
knowledge — keeps the system prompt small.
"""
from __future__ import annotations

import re
from pathlib import Path

from rich_senpai.core.logging_setup import get_logger


log = get_logger(__name__)


_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)", re.DOTALL)


class SkillLoader:
    def __init__(self, skills_dir: Path) -> None:
        self.skills_dir = skills_dir
        self.skills_dir.mkdir(parents=True, exist_ok=True)

        self.skills: dict[str, dict[str, str]] = {}

        self._scan()

    def _scan(self) -> None:
        self.skills.clear()

        if not self.skills_dir.exists():
            log.warning("skills dir %s does not exist", self.skills_dir)
            return

        for skill_file in sorted(self.skills_dir.rglob("SKILL.md")):
            body = skill_file.read_text(encoding="utf-8").strip()

            lines = body.splitlines()

            desc = lines[0].strip() if lines else ""

            skill_name = skill_file.parent.name

            self.skills[skill_name] = {
                "description": desc,
                "body": body,
                "path": str(skill_file),
            }

    def reload(self) -> None:
        self._scan()

    def descriptions(self) -> str:
        if not self.skills:
            return "(no skills)"

        return "\n".join(
            f"  - {name}: {skill['description']}"
            for name, skill in self.skills.items()
        )

    def load(self, name: str) -> str:
        skill = self.skills.get(name)

        if not skill:
            available = ", ".join(sorted(self.skills.keys())) or "(none)"
            return f"error: unknown skill '{name}'. Available: {available}"

        return (
            f"<skill name=\"{name}\">\n"
            f"{skill['body']}\n"
            f"</skill>"
        )