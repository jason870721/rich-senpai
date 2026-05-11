"""Tests for SkillLoader — discovery, loading, caching."""

import tempfile
from pathlib import Path

from rich_senpai.core.unit.manager.skills import SkillLoader


# ── helpers ────────────────────────────────────────────────────────────


def _write_skill(base: Path, name: str, body: str) -> Path:
    """Write a SKILL.md file. body's first line becomes description."""
    skill_dir = base / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(body)
    return skill_dir


def _make_loader(skills_dir: Path) -> SkillLoader:
    """Create a SkillLoader — skills must already exist on disk."""
    return SkillLoader(skills_dir=skills_dir)


# ── descriptions ───────────────────────────────────────────────────────


def test_descriptions_empty_dir():
    with tempfile.TemporaryDirectory() as tmp:
        skills_dir = Path(tmp) / "skills"
        loader = SkillLoader(skills_dir=skills_dir)
        desc = loader.descriptions()
        assert desc == "(no skills)"


def test_descriptions_shows_skill_names():
    with tempfile.TemporaryDirectory() as tmp:
        skills_dir = Path(tmp) / "skills"
        _write_skill(skills_dir, "git", body="Git helper skill\n\nUse `git commit` safely.")
        _write_skill(skills_dir, "python", body="Python coding guidelines\n\nFollow PEP 8.")
        loader = SkillLoader(skills_dir=skills_dir)
        desc = loader.descriptions()
        assert "git" in desc
        assert "python" in desc


def test_descriptions_includes_first_line_as_description():
    with tempfile.TemporaryDirectory() as tmp:
        skills_dir = Path(tmp) / "skills"
        _write_skill(skills_dir, "commit", body="Safe git commit workflows\n\nMore body.")
        loader = SkillLoader(skills_dir=skills_dir)
        desc = loader.descriptions()
        assert "Safe git commit workflows" in desc


# ── load ───────────────────────────────────────────────────────────────


def test_load_skill_returns_body_wrapped_in_tags():
    with tempfile.TemporaryDirectory() as tmp:
        skills_dir = Path(tmp) / "skills"
        _write_skill(skills_dir, "git", body="Git helper\n\nUse `git commit` safely.")
        loader = SkillLoader(skills_dir=skills_dir)
        body = loader.load("git")
        assert 'skill name="git"' in body
        assert "Git helper" in body
        assert "git commit" in body


def test_load_unknown_skill_returns_error_string():
    with tempfile.TemporaryDirectory() as tmp:
        skills_dir = Path(tmp) / "skills"
        loader = SkillLoader(skills_dir=skills_dir)
        result = loader.load("nonexistent")
        assert "unknown skill 'nonexistent'" in result


def test_load_caches_result():
    with tempfile.TemporaryDirectory() as tmp:
        skills_dir = Path(tmp) / "skills"
        _write_skill(skills_dir, "cached", body="original first line\noriginal body")
        loader = SkillLoader(skills_dir=skills_dir)
        loader.load("cached")
        # Modify the file — loader should return cached version.
        (skills_dir / "cached" / "SKILL.md").write_text("changed first line\nchanged body")
        body = loader.load("cached")
        assert "original first line" in body
        assert "changed" not in body


def test_reload_refreshes_cache():
    with tempfile.TemporaryDirectory() as tmp:
        skills_dir = Path(tmp) / "skills"
        _write_skill(skills_dir, "refresh", body="original\noriginal body")
        loader = SkillLoader(skills_dir=skills_dir)
        loader.load("refresh")
        (skills_dir / "refresh" / "SKILL.md").write_text("new first line\nnew body")
        loader.reload()
        body = loader.load("refresh")
        assert "new first line" in body
        assert "original" not in body


def test_load_multiple_skills():
    with tempfile.TemporaryDirectory() as tmp:
        skills_dir = Path(tmp) / "skills"
        _write_skill(skills_dir, "a", body="Skill A desc\n\nbody A")
        _write_skill(skills_dir, "b", body="Skill B desc\n\nbody B")
        loader = SkillLoader(skills_dir=skills_dir)
        assert "body A" in loader.load("a")
        assert "body B" in loader.load("b")


def test_load_skill_directory_name_used_as_key():
    with tempfile.TemporaryDirectory() as tmp:
        skills_dir = Path(tmp) / "skills"
        skill_dir = skills_dir / "plain"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("Plain skill\n\nJust body.")
        loader = SkillLoader(skills_dir=skills_dir)
        body = loader.load("plain")
        assert "Plain skill" in body


def test_skills_dir_created_on_init():
    with tempfile.TemporaryDirectory() as tmp:
        skills = Path(tmp) / "nested" / "skills"
        loader = SkillLoader(skills_dir=skills)
        assert skills.is_dir()
