"""Manager unit — process-wide singletons held by core.state."""
from rich_senpai.core.unit.manager.background import BackgroundManager
from rich_senpai.core.unit.manager.skills import SkillLoader
from rich_senpai.core.unit.manager.todos import TodoManager

__all__ = ["BackgroundManager", "SkillLoader", "TodoManager"]
