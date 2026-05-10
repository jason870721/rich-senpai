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
        └── RichSenpaiAgent (lead agent loop)
              ├── LLMClient (Anthropic / Ollama)
              ├── AgentCore (tool execution, ReAct loop)
              ├── AgentTeam (teammate lifecycle)
              ├── AgentMessaging (in-process message bus)
              └── TaskManager (file-backed task board)
```

### How it works

1. **The lead agent** runs a continuous ReAct loop: observe context → reason → act (call tools) → repeat
2. **Teammates** are spawned as background workers with their own role, prompt, and ReAct loop
3. **Communication** happens via a thread-safe in-memory message bus (FIFO per recipient)
4. **Tools** are registered declaratively via `@Tool(name, description, params)` decorator and executed by the core
5. **Tasks** are stored as JSON documents on disk, enabling shared work across agents and restarts
6. **Skills** are Markdown files loaded on demand to inject domain knowledge into agent context

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

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure your LLM provider
cp .env.example .env
# Edit .env and set:
#   - LLM_PROVIDER=anthropic (or ollama)
#   - ANTHROPIC_API_KEY=<your-key>   (if using Anthropic)
#   - OLLAMA_MODEL=<model-name>       (if using Ollama)

# 5. Run the TUI
python main.py
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

## SDK version

**Python 3.14.3**

## Project structure

```
rich-senpai/
├── main.py                     # Entry point
├── requirements.txt            # Dependencies
├── .env.example                # Configuration template
├── .gitignore
├── README.md                   # This file
├── .senpai/
│   └── skills/                 # Loadable skill definitions (Markdown)
├── core/
│   ├── __init__.py
│   ├── agent_core.py           # ReAct loop, tool registry, tool execution
│   ├── config.py               # Settings from env + YAML config file
│   ├── llm/
│   │   ├── __init__.py         # LLMClient base class + build_default_client()
│   │   ├── base.py             # Abstract LLMClient + response types
│   │   ├── anthropic_client.py # Anthropic API adapter
│   │   └── ollama_client.py    # Ollama API adapter
│   ├── messaging.py            # Thread-safe in-process message bus
│   ├── skills.py               # Skill loading from .senpai/skills/
│   ├── tasks_file.py           # File-backed JSON task board
│   └── team.py                 # Teammate lifecycle management
└── session_tui/
    ├── __init__.py
    ├── tui.py                  # Textual TUI with live log, status, and chat
    └── theme.py                # Rich ThemedStyle definitions
```

## Adding a new tool

Tools are registered with the `@tool()` decorator. Each tool is a function with:

1. A docstring that serves as the tool description
2. An `annotated params` signature (type hints become JSON schema)

```python
from core.agent_core import tool

@tool
def hello_world(name: str) -> str:
    """Print a greeting."""
    return f"Hello, {name}!"
```

The tool automatically becomes available to all agents in the system.

## Adding a new skill

Skills live in `.senpai/skills/<skill-name>/SKILL.md`. Each skill is a single Markdown file with:

1. A `# Title` heading (used as the skill name)
2. Frontmatter `name` field
3. Sections describing purpose, workflow, rules, and examples

The skill is loaded on demand via the `load_skill` tool, which injects its content into the agent's conversation context.

## Pending features

### Short-term
* Core Refactor: core folder is getting too big, need to break it down into submodules (e.g. llm/, unit/, etc.)
* Memory System - Growable Agent.

### Long-term
* Veronica - A web service that lives with a lead agent.

<br>

## License

MIT
