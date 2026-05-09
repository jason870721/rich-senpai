"""Skill loader (s_full.py s05 mechanism).

A "skill" is a SKILL.md file under skills/ with optional YAML-ish
frontmatter (name + description) and a markdown body. The agent picks one
up at runtime via the load_skill tool when it needs specialized
knowledge — keeps the system prompt small.
"""
from __future__ import annotations

import re
from pathlib import Path


_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)", re.DOTALL)


class SkillLoader:
    def __init__(self, skills_dir: Path) -> None:
        self.skills_dir = skills_dir
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.skills: dict[str, dict[str, object]] = {}
        self._scan()

    def _scan(self) -> None:
        if not self.skills_dir.exists():
            return
        for f in sorted(self.skills_dir.rglob("SKILL.md")):
            text = f.read_text(encoding="utf-8")
            match = _FRONTMATTER_RE.match(text)
            meta: dict[str, str] = {}
            body = text
            if match:
                for line in match.group(1).strip().splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        meta[k.strip()] = v.strip()
                body = match.group(2).strip()
            name = meta.get("name", f.parent.name)
            self.skills[name] = {"meta": meta, "body": body, "path": str(f)}

    def reload(self) -> None:
        self.skills.clear()
        self._scan()

    def descriptions(self) -> str:
        if not self.skills:
            return "(no skills)"
        return "\n".join(
            f"  - {n}: {s['meta'].get('description', '-')}"
            for n, s in self.skills.items()
        )

    def load(self, name: str) -> str:
        s = self.skills.get(name)
        if not s:
            available = ", ".join(self.skills.keys()) or "(none)"
            return f"error: unknown skill '{name}'. Available: {available}"
        return f"<skill name=\"{name}\">\n{s['body']}\n</skill>"
