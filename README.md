# Rich Senpai

> 🍣 An autonomous multi-agent system for trading, built in a day.

<br>

---

<br>

## What is this?

Rich Senpai is a **multi-agent trading system** where a lead agent coordinates specialized teammate agents to collaboratively solve tasks — primarily in financial markets, but extensible to any domain.

### Key features

- **Multi-agent architecture** — A lead agent spawns, manages, and communicates with specialized teammate agents via an in-process message bus
- **Tool ecosystem** — Agents have access to file I/O, shell commands, HTTP requests, git operations, task boards, and more
- **Skill system** — Load domain-specific knowledge (skills) on demand to augment agent capabilities
- **TUI interface** — A rich terminal UI for monitoring agent conversations and system state in real-time
- **Configurable LLM backend** — Plug in Anthropic or Ollama as the LLM provider
- **File-backed task board** — Shared task persistence survives process restarts; teammates pick up unclaimed tasks automatically

### Architecture at a glance

```
main.py (entry point)
  └── session_tui/tui.py (Textual TUI)
        └── AgentCore (lead ReAct loop, core/unit/agent/agent_core.py)
              ├── LLMClient        (core/llm/, Anthropic or Ollama)
              ├── tool_register    (tools/tool_register.py, registry + dispatch)
              ├── TeammateManager  (core/unit/team/team.py, teammate lifecycle)
              ├── MessageBus       (core/unit/team/messaging.py, JSONL inbox bus)
              ├── TaskManager      (core/unit/team/tasks_file.py, file-backed task board)
              ├── BackgroundManager (core/unit/manager/background.py, fire-and-forget shell)
              ├── SkillLoader      (core/unit/manager/skills.py)
              └── TodoManager      (core/unit/manager/todos.py, in-memory todo list)
```

The singletons above are constructed once in `core/state.py` and reached by
tools as `from core import state` (e.g. `state.BUS.send(...)`).

### How it works

1. **The lead agent** runs a continuous ReAct loop: observe context → reason → act (call tools) → repeat (`core/unit/agent/agent_core.py`).
2. **Teammates** are spawned as `asyncio.Task` workers with their own role, prompt, and ReAct loop (`core/unit/team/team.py`); a short-lived **subagent** variant powers the `task` tool for one-shot delegated work (`core/unit/subagent/subagent.py`).
3. **Communication** happens through a thread-safe `MessageBus` backed by per-recipient JSONL inbox files (`core/unit/team/messaging.py`).
4. **Tools** are plain Python modules under `tools/<bucket>/<tool>.py`. Each module exports a `SPEC` dict (Anthropic-shaped tool schema) and a top-level callable whose name matches the module — no decorator needed. `tools/tool_register.py` imports each module by reference, collects `TOOL_SPECS`, and dispatches `tool_use` blocks through `call_tool()`. See `tools/README.md` for the contract.
5. **Tasks** are stored as JSON documents on disk by `TaskManager`, enabling shared work across agents and restarts.
6. **Skills** are Markdown files (`.senpai/skills/<name>/SKILL.md`) loaded on demand by the `load_skill` tool to inject domain knowledge into the agent's context.
7. **Conversation compaction** keeps the rolling context within token budget — `microcompact` stubs old tool results in place, `auto_compact` LLM-summarizes the full transcript when the budget is exceeded (`core/unit/agent/compaction.py`).

<br>

## How to start?

### Prerequisites

- **Python 3.14** (developed on 3.14.3)
- **API key** for your LLM provider:
  - Anthropic: `ANTHROPIC_API_KEY` env var, or
  - Ollama: running `ollama serve` locally

### Quick start

```bash
# 1. Clone and enter the project
git clone <repo-url>
cd rich-senpai

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# 3. Install the package (editable for development; drop -e for plain installs)
pip install -e .
# For dev (tests, linting, type-check):
#   pip install -e ".[dev]"

# 4. Configure your LLM provider
cp .env.example .env
# Edit .env and set:
#   - LLM_PROVIDER=anthropic (or ollama)
#   - ANTHROPIC_API_KEY=<your-key>   (if using Anthropic)
#   - OLLAMA_MODEL=<model-name>       (if using Ollama)

# 5. Run the TUI
rich-senpai
```

### TUI controls

The terminal UI supports keyboard navigation and commands:

| Key | Action |
|-----|--------|
| `Tab` / `Shift+Tab` | Switch between panels (Message Log / System Status / Chat) |
| `1`, `2`, `3` | Jump to panel 1, 2, or 3 |
| `q` | Quit the application |
| `Space` | Pause / resume live updates |
| Arrow keys | Navigate message history |
| `Enter` | Send chat message |


### Chat commands

Type these in the chat panel:

| Command | Action |
|---------|--------|
| `!status` | Show teammate and task board status |
| `!clear` | Clear message log |
| `!help` | Show help |

<br>

## SDK version

**Python 3.+**

<br>

## Project structure

```
rich-senpai/
├── pyproject.toml                   # PEP 621 metadata, deps, entry point, ruff/pyright/pytest config
├── requirements.txt                 # Legacy install path (mirrors pyproject deps)
├── .env.example                     # Configuration template (LLM provider, paths, knobs)
├── README.md
├── LICENSE
├── .senpai/                         # Runtime artifacts (created on first run; gitignored)
│   └── skills/                      # Loadable skill bundles (<name>/SKILL.md)
│
└── src/rich_senpai/                 # Importable package
    ├── __init__.py                  # __version__
    ├── cli.py                       # Console entrypoint — wires logging then launches the TUI
    │
    ├── core/                        # Agent runtime
    │   ├── __init__.py              # Public API: AgentCore, CycleResult, ToolCall
    │   ├── config.py                # All tunable constants (env-driven, single source of truth)
    │   ├── state.py                 # Process-wide singletons (TODO, SKILLS, TASK_MGR, BG, BUS, …)
    │   ├── logging_setup.py         # File-based logging + payload clipping helpers
    │   ├── llm/                     # Provider-neutral LLM layer
    │   │   ├── base.py              #   Abstract LLMClient + Message / block types
    │   │   ├── anthropic_client.py  #   Anthropic adapter
    │   │   └── ollama_client.py     #   Ollama adapter
    │   └── unit/                    # Categorized sub-systems
    │       ├── agent/               #   Lead ReAct loop
    │       │   ├── agent_core.py    #     The loop itself (compaction, dispatch, nags)
    │       │   ├── compaction.py    #     microcompact / auto_compact / estimate_tokens
    │       │   └── sys_prompt.py    #     System prompt builder (config + live skills)
    │       ├── subagent/
    │       │   └── subagent.py      #   Short-lived ReAct loop for the `task` tool
    │       ├── team/                #   Multi-agent collaboration
    │       │   ├── team.py          #     TeammateManager — persistent asyncio teammates
    │       │   ├── tasks_file.py    #     TaskManager — JSON-per-task on disk
    │       │   └── messaging.py     #     MessageBus + plan/shutdown request registries
    │       └── manager/             #   Singleton-backed managers
    │           ├── todos.py         #     TodoManager (ephemeral in-process todo list)
    │           ├── skills.py        #     SkillLoader (.senpai/skills discovery)
    │           └── background.py    #     BackgroundManager (fire-and-forget shell tasks)
    │
    ├── tools/                       # Lead-agent tool surface
    │   ├── README.md                # Module contract (SPEC + matching callable, ToolResult)
    │   ├── tool_register.py         # Imports every tool, builds TOOL_SPECS + call_tool()
    │   ├── tool_result.py           # ToolResult dataclass + as_text helper
    │   ├── file_access/             #   read_file, write_file, edit_file, grep, _diff (helper)
    │   ├── shell/                   #   bash, background_run, check_background, http_request
    │   ├── task_board/              #   task_create / get / update / list / claim_task
    │   ├── delegation/              #   task, spawn_teammate, list_teammates
    │   ├── messaging/               #   send_message, read_inbox, broadcast, shutdown_request, plan_approval
    │   └── memory/                  #   update_short_memory, todo_write, load_skill, compress, idle, wait
    │
    └── session_tui/                 # Textual TUI front-end
        ├── tui.py                   # App shell — chat input, panels, event loop
        ├── events.py                # Render agent events → log lines
        ├── commands.py              # In-chat slash commands (/clear, /help, …)
        ├── panels.py                # Live status panels (background, coworkers, todos)
        ├── render.py / widgets.py / welcome.py / style.py
        └── ...
```

<br>

## Adding a new tool

Tools are plain Python modules — there is no decorator. Each module exports a
`SPEC` dict (Anthropic-shaped) and a top-level callable whose attribute name
matches the module's last path segment.

1. Pick the right bucket under `tools/` (e.g. `tools/file_access/` for file ops,
   `tools/shell/` for shell-style commands, `tools/messaging/` for inter-agent
   messages). Create `tools/<bucket>/<your_tool>.py`.
2. Define `SPEC` and a matching-name handler that returns `ToolResult`. Use
   `ok=False` to flag a failure the TUI should render in red.
3. Re-export the new module from `tools/<bucket>/__init__.py`.
4. Add the module reference to the appropriate group in
   `tools/tool_register.py::TOOL_GROUPS`.

```python
# tools/file_access/hello.py
from tools.tool_result import ToolResult


SPEC = {
    "name": "hello",
    "description": "Print a greeting.",
    "input_schema": {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
}


def hello(name: str) -> ToolResult:
    return ToolResult(text=f"Hello, {name}!")
```

`TOOL_SPECS`, `TOOL_HANDLERS`, and `call_tool()` pick the tool up automatically
— no other edits required. See `tools/README.md` for the full contract.

<br>

## Adding a new skill

Skills live in `.senpai/skills/<skill-name>/SKILL.md`. Each skill is a single Markdown file with:

1. A `# Title` heading (used as the skill name)
2. Frontmatter `name` field
3. Sections describing purpose, workflow, rules, and examples

The skill is loaded on demand via the `load_skill` tool, which injects its content into the agent's conversation context.

<br>

## Pending features

### Short-term
* Memory System — Growable Agent.

### Long-term
* Veronica — A web service that lives with a lead agent.

<br>

## License

MIT
