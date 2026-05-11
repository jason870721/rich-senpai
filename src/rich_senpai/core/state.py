"""Process-wide singletons for the new mechanisms.

Tools are stateless functions in this codebase. The new managers
(TodoManager, SkillLoader, TaskManager-on-disk, BackgroundManager,
MessageBus, TeammateManager) hold state, so the tool layer reaches them
through this module instead of carrying instances around. The agent
core also imports from here.

Names from s_full.py are preserved so the mental model stays the same.
The LEAD_NAME constant is what `send_message`, `read_inbox`, and
`broadcast` use as their sender / inbox identity.

All filesystem paths come from `core.config` so the project has one
canonical workdir even after a chdir. The eager singletons below are
constructed with explicit dirs to avoid the previous
"`Path.cwd()`-at-import-time" pattern.

LLM construction is deferred — building AnthropicLLMClient eagerly at
import time would crash any tooling that imports `core` without
ANTHROPIC_API_KEY set (tests, --help, etc.). Tools and agent_core call
get_llm() on demand.
"""
from __future__ import annotations

from rich_senpai.core import config
from rich_senpai.core.llm import LLMClient
from rich_senpai.core.unit.manager import BackgroundManager, SkillLoader, TodoManager
from rich_senpai.core.unit.team import MessageBus, TaskManager, TeammateManager


# Re-exported for backwards compatibility with code that still does
# `state.WORKDIR` / `state.SKILLS_DIR`. New code should prefer
# `core.config.WORKDIR` so there's a single source of truth.
WORKDIR = config.WORKDIR
SKILLS_DIR = config.SKILLS_DIR
LEAD_NAME = "lead"


TODO: TodoManager = TodoManager()
SKILLS: SkillLoader = SkillLoader(config.SKILLS_DIR)
TASK_MGR: TaskManager = TaskManager(tasks_dir=config.TASKS_DIR)
BG: BackgroundManager = BackgroundManager(workdir=config.WORKDIR)
BUS: MessageBus = MessageBus(inbox_dir=config.INBOX_DIR)

_llm: LLMClient | None = None
_team: TeammateManager | None = None


def get_llm() -> LLMClient:
    global _llm
    if _llm is None:
        from rich_senpai.core.llm import build_default_client
        _llm = build_default_client()
    return _llm


def set_llm(client: LLMClient) -> None:
    """Inject a shared LLMClient so subagent and teammate calls go
    through the same provider/instance the lead uses."""
    global _llm, _team
    _llm = client
    _team = TeammateManager(
        llm=client,
        bus=BUS,
        task_mgr=TASK_MGR,
        team_dir=config.TEAM_DIR,
    )


def get_team() -> TeammateManager:
    global _team
    if _team is None:
        _team = TeammateManager(
            llm=get_llm(),
            bus=BUS,
            task_mgr=TASK_MGR,
            team_dir=config.TEAM_DIR,
        )
    return _team

# reset() is called by tui.action_clear_history() when the user input /clear
# clean: BG + TODOList
def reset():
    TODO.reset()
    BG.reset()