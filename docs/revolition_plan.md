# rich-senpai 2.0 — Revolution Roadmap

> Bring rich-senpai to Claude-Code-grade quality as an open-source CLI tool, in
> one quarter, foundation first.

## North star

A `pip install rich-senpai` installable, MCP-capable, multi-agent TUI that
matches Claude Code's single-agent UX feature-for-feature *and* keeps the
persistent-teammate + shared-task-board model as a differentiator.

## Guiding principles

1. **Foundation before features.** No new feature lands without tests, types,
   and CI coverage.
2. **Parity then differentiation.** Stop inventing where Claude Code already
   solved it (read-before-edit, slash palette, plan mode); keep inventing where
   we already lead (persistent teammates, plan_approval).
3. **One source of truth for config.** `core/config.py` stays the only place
   numbers are tuned; new knobs go through env + dataclass.
4. **Provider-neutral.** Every feature must work on Anthropic *and* Ollama.
   Where a provider can't (e.g. caching on Ollama), degrade gracefully.
5. **Open-source-first.** Public roadmap, semver, changelog, contributing
   guide, code of conduct from day one.

---

## Milestone 1 — Foundation (Month 1)

Goal: nothing user-visible regresses, but the project becomes safe to evolve.

### 1.1 Packaging & distribution

- **`pyproject.toml`** (PEP 621): metadata, deps, dev-deps, console entrypoint
  `rich-senpai = "rich_senpai.cli:main"`.
- Rename top-level `main.py` → `src/rich_senpai/cli.py`; adopt `src/` layout.
- Pin Python `>=3.12,<3.15` (currently 3.14-only — narrow this).
- Add `__version__` in `src/rich_senpai/__init__.py`; wire into TUI status row.
- Pre-release wheel + sdist build via `python -m build`; verify locally.

### 1.2 Tests & CI

- `tests/` directory with pytest layout.
- **Unit tests** for: `tools/tool_register.py::call_tool`, `compaction.py`
  (`microcompact`, `auto_compact`, `estimate_tokens`), `MessageBus` JSONL
  round-trip, `TaskManager` JSON load/save + `blockedBy` cascade, `SkillLoader`
  discovery, `_diff.DiffParser` happy + fuzzy fail paths.
- **TUI tests** with `Textual.App.run_test()` + `Pilot`: command parsing for
  every `/help`, `/clear`, `/compact`, `/tasks`, `/team`, `/inbox`, `/copy`,
  `/quit`; paste-collapse round-trip; typewriter reveal commits final markdown
  block.
- **Integration test** using a mock `LLMClient` that scripts a tool_use → tool
  loop → final text response.
- Target: **60% line coverage** by end of milestone. Track via `coverage.py`.
- GitHub Actions `.github/workflows/ci.yml`: matrix on Python 3.12/3.13/3.14
  and macOS/Linux. Steps: ruff check, pyright, pytest with coverage upload.

### 1.3 Lint, types, hooks

- `ruff` config in `pyproject.toml` (rules: `E,F,I,UP,B,SIM,RUF`; line length
  100; ignore generated diff helpers).
- `pyright` strict on `src/rich_senpai/`, basic on `tests/`; replace `Any`
  hints in `core/llm/base.py` (Message/Block types) with proper `TypedDict`
  or `pydantic.BaseModel`.
- `pre-commit` config: ruff format + check, pyright, end-of-file-fixer,
  trailing-whitespace, debug-statements.
- Convert broad `except Exception as exc  # noqa: BLE001` sites in
  `core/unit/team/team.py`, `core/unit/manager/background.py`,
  `core/unit/subagent/subagent.py` to specific exception groups where the
  surface is known.

### 1.4 Security hardening

- **Path-traversal guard** in `tools/file_access/read_file.py`,
  `write_file.py`, `edit_file.py`: resolve paths and verify
  `.is_relative_to(WORKDIR)`; allow opt-in `--allow-outside-workdir` via tool
  arg, default deny. Same for `grep` path arg.
- **Secret redaction** in `core/logging_setup.py`: regex pass over payloads
  for `sk-ant-`, `sk-`, `ghp_`, `xoxp-`, AWS keys, generic
  `*_KEY=` / `*_TOKEN=` patterns; redact to `[REDACTED:<kind>]`. Apply at the
  log formatter, not just at call sites.
- **Bash permission tiers** in `tools/shell/bash.py`: introduce
  `BASH_PERMISSION_MODE` env (`allow_all` / `confirm_destructive` /
  `deny_destructive`); the middle tier intercepts a denylist (`rm -rf`,
  `dd`, `mkfs`, force-push, `:(){...}:&`) and emits a `bash_confirm_required`
  event the TUI displays as a yes/no prompt.
- Document threat model in `docs/SECURITY.md`.

### 1.5 Observability & cost

- Token usage is already in `LLMResponse.usage` — surface it: add an in-memory
  `SessionStats` in `core/state.py` (cumulative input/output tokens per
  model, tool-call counts, dollars-spent estimate using a public rate table).
- TUI: extend the stats row beneath input to show `cost: $X.XXX` for
  Anthropic; track tokens-only for Ollama.
- Structured event log: emit JSONL events alongside the text log so
  third-party tools (e.g. Langfuse) can ingest.

### 1.6 Streaming + caching foundations (enables many UX wins later)

- **Anthropic streaming** in `core/llm/anthropic_client.py`: switch to
  `client.messages.stream(...)`; expose a `stream_create_message` async
  generator on `LLMClient` returning `(event_kind, payload)` chunks.
- **Ollama streaming** in `core/llm/ollama_client.py`: pass `stream=True` and
  yield analogous chunks.
- **Prompt caching** for Anthropic: mark system prompt and tool specs with
  `cache_control: {"type": "ephemeral"}`; re-cache when skills list changes.
- Refactor `AgentCore._await_llm` to consume the streaming generator and
  forward token deltas to `on_event` as `assistant_text_delta` events.
- TUI: replace the post-hoc typewriter reveal with real-token streaming when
  available; keep typewriter as fallback for Ollama models that don't stream
  tool calls cleanly.

#### Milestone 1 exit criteria

- `pip install -e .` works; `rich-senpai` launches the TUI.
- `pytest` runs green locally and in CI on three Python versions.
- `ruff check .` and `pyright` are clean.
- No file tool can write outside the workdir without explicit override.
- Logs no longer contain `sk-ant-...` even when an agent echoes the key.
- Anthropic responses stream visibly into the TUI; cache hit rate visible in
  stats.

---

## Milestone 2 — Tool surface + UX parity (Month 2)

Goal: a returning Claude Code user feels at home.

### 2.1 File tools

- **Read-before-edit enforcement.** `AgentCore` tracks `set[Path]` of files
  the current cycle has read; `edit_file` and `write_file` (for existing
  files) return `ok=False` with a clear message if the path isn't in the
  set. Cycle-scoped, not session-scoped.
- **`glob` tool** under `tools/file_access/glob.py`: `pattern` + optional
  `path`, returns matching files sorted by mtime (matches Claude Code
  semantics). Reuse the skip-list from `grep.py`.
- **`multi_edit` tool**: list of `(old, new)` pairs applied atomically — all
  must hit, or none do. Avoids "edit twice" round-trips agents do today.
- **Diff renderer parity**: surface both `--- a/` / `+++ b/` headers and hunk
  metadata to TUI (already half-done in `session_tui/render.py`).

### 2.2 Web tools

- **`web_fetch`** under `tools/web/web_fetch.py`: `httpx.AsyncClient` with
  redirect cap, 5 MB response cap, content-type allowlist
  (`text/*`, `application/json`, `application/xml`); strips scripts via
  `beautifulsoup4`; returns markdown via `markdownify`.
- **`web_search`** under `tools/web/web_search.py`: backend pluggable
  (`SEARCH_BACKEND=brave|tavily|serper`), returns top-N
  `{title, url, snippet}` rows. Keys via env.
- Both tools respect a global `WEB_TOOLS_ENABLED` env to allow air-gapped use.

### 2.3 LSP integration

- New `core/lsp/` package with a thin client to language servers via JSON-RPC
  over stdio. First server: **pyright** (already in venv). Second: **gopls**
  via a config-driven launcher.
- Tools: `lsp_definition(symbol)`, `lsp_references(symbol)`,
  `lsp_hover(file, line, col)`, `lsp_diagnostics(file?)`.
- Skip launching when no project file matches (no `pyproject.toml`, etc.).

### 2.4 Subagent worktree isolation

- `tools/delegation/task.py` accepts `isolation: "worktree" | "none"`; when
  worktree, create `git worktree add` under `.senpai/worktrees/<task_id>`,
  run the subagent there, return branch + diff on completion. Auto-clean if
  no changes.
- Extend to `spawn_teammate` as opt-in for risky long-running roles.

### 2.5 TUI parity surface

- **Slash-command palette**: typing `/` opens a fuzzy autocomplete dropdown
  built on top of `session_tui/commands.py::REGISTRY` plus skills (`/skill:`)
  and tools (`/tool:` for debug). Implement as a Textual overlay widget.
- **@-mention file completion**: typing `@` in the input opens a file picker
  filtered by typed prefix; auto-injects a `read_file` call when submitted.
  Backed by `pathspec` for gitignore-aware listing.
- **Image paste**: detect image clipboard via platform integration
  (`pyperclip3` / `Quartz` / `xclip -t image/png`); convert to base64 image
  blocks. Requires extending `core/llm/base.py` content types.
- **Model switcher**: `/model` command + status-row click target; rebuilds
  the LLM client without dropping conversation history.
- **Plan mode**: `/plan` command sets `AgentCore.plan_mode = True`; system
  prompt gains a "do not edit; produce a plan" guardrail; only an explicit
  `exit_plan_mode` tool lifts it. Mirrors Claude Code semantics.
- **Token-budget warning**: when `estimate_tokens` crosses 75% of
  `TOKEN_THRESHOLD`, the status row turns gold and the input hint suggests
  `/compact`.
- **Search in log**: `Ctrl+F` in the message log opens a Textual `Input`
  that highlights matches and supports next/prev.
- **Resume**: `rich-senpai resume <session-id>` CLI subcommand reads the
  transcripts snapshotted by `compaction.py::auto_compact` and rehydrates
  the message list. List sessions via `rich-senpai sessions`.

### 2.6 Token counting + provider parity

- Replace `len(json) // 4` heuristic in `core/unit/agent/compaction.py` with
  provider-aware counting:
  - Anthropic: `client.beta.messages.count_tokens(...)` (real API).
  - Ollama: tiktoken-cl100k as best-effort fallback.
- Parallel tool-use: enable `parallel_tool_use=True` on Anthropic; dispatch
  the returned `ToolUseBlock` list concurrently in
  `AgentCore._dispatch_tool_uses` via `asyncio.gather`.

#### Milestone 2 exit criteria

- Edit/write requires a prior read in the same cycle; tests cover both
  passes and the violation path.
- `web_fetch` + `web_search` work end-to-end against live endpoints (skipped
  in CI without keys).
- `lsp_definition` returns a real location for `AgentCore` in this repo.
- `/plan` mode visibly blocks edits and exits cleanly.
- Image paste into TUI is forwarded to Anthropic and gets a reasoned reply.
- Anthropic parallel tool calls visibly issue concurrent tool events.

---

## Milestone 3 — MCP, polish, release (Month 3)

Goal: ship `v0.1.0` on PyPI with a story, not just a tarball.

### 3.1 MCP client support

- New `core/mcp/` package: connect to MCP servers over stdio per a project
  `.mcp.json` (Claude Code shape). Tools from MCP servers are exposed as
  `mcp__<server>__<tool>`.
- **Deferred tool loading**: when the combined tool list exceeds N (default
  64), expose only an in-house `tool_search` tool that lets the agent
  request specific MCP tool schemas on demand (matches the `ToolSearch`
  pattern).
- Ship `.mcp.json.example` with: gopls, a generic filesystem MCP, a Postgres
  read-only MCP.

### 3.2 Notebook editing

- `tools/file_access/notebook_edit.py`: edit a single cell by index, replace
  cell source, append cell. Use `nbformat` for round-trip safety.

### 3.3 Scheduled / looped agents

- `core/scheduler/` with a cron-like loop on top of `asyncio`. Two surfaces:
  - **`/loop <interval> <prompt>`** — TUI command that re-injects a prompt
    on a cadence until cancelled.
  - **`/schedule <cron> <prompt>`** — persists to `.senpai/schedule.json`,
    fires when the TUI is running; future work: detached daemon.

### 3.4 Multi-agent enhancements (the differentiator)

- **Per-teammate model**: `spawn_teammate(model=...)` so a cheap teammate
  can run on Haiku/qwen while the lead runs on Opus/Sonnet.
- **Teammate transcripts viewable in TUI**: a new `/teammate <name>` command
  pops a panel with that teammate's live message log.
- **Task board UI** improvements: tree view of `blockedBy` graph; filter by
  owner/status; click-to-claim.

### 3.5 Documentation site

- `mkdocs-material` site under `docs/` with these top-level pages:
  Quickstart, Architecture, Tool authoring, Skill authoring, Multi-agent
  guide, MCP guide, Security model, Troubleshooting, Contributing,
  Changelog.
- Build and deploy via GH Pages on tag push.
- Move the existing TUI dev guide from `session_tui/README.md` into
  `docs/internals/tui.md` (keep a stub link in the source dir).

### 3.6 Release engineering

- **Semver from `v0.1.0`**. `CHANGELOG.md` in Keep-a-Changelog format.
- Tag-driven release workflow: `.github/workflows/release.yml` builds wheel,
  pushes to PyPI via OIDC, attaches sdist to the GH release, and updates
  the docs site.
- `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, issue + PR templates.
- A clear `docs/ROADMAP.md` reflecting this file plus issues labeled
  `roadmap/M2`, `roadmap/M3`, etc.

#### Milestone 3 exit criteria

- `pip install rich-senpai` from PyPI works in a clean venv.
- `.mcp.json` with at least one server (gopls or filesystem) functions
  inside rich-senpai.
- Docs site live at a GH Pages URL.
- `v0.1.0` tag exists with a populated changelog and release notes.

---

## Critical files / modules touched

| Area | Files |
|---|---|
| Packaging | `pyproject.toml` (new), `main.py` → `src/rich_senpai/cli.py` |
| Streaming + caching | `core/llm/base.py`, `core/llm/anthropic_client.py`, `core/llm/ollama_client.py`, `core/unit/agent/agent_core.py` (`_await_llm`, ~L465) |
| Compaction | `core/unit/agent/compaction.py` (L28–L97: token counting + auto_compact window) |
| File tools | `tools/file_access/{read_file,write_file,edit_file,grep}.py`; new `glob.py`, `multi_edit.py` |
| Web / LSP / MCP | new `tools/web/`, `core/lsp/`, `core/mcp/` |
| Subagent worktree | `tools/delegation/task.py`, `core/unit/subagent/subagent.py` |
| TUI parity | `session_tui/commands.py` (REGISTRY), `session_tui/widgets.py` (`HistoryInput`); new `palette.py`, `image_paste.py`, `mention_completer.py` |
| Security | `tools/shell/bash.py`, `core/logging_setup.py`; new `docs/SECURITY.md` |
| Observability | `core/state.py` (`SessionStats`), `core/logging_setup.py` |
| Tests + CI | new `tests/`, `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `.pre-commit-config.yaml` |
| Docs | `docs/` (mkdocs site), `CHANGELOG.md`, `CONTRIBUTING.md` |

## Reused utilities

- `tools/tool_result.py::ToolResult` — universal tool return type; all new
  tools use it.
- `tools/file_access/_diff.py::DiffParser` / `DiffApplier` — reuse for
  `multi_edit` and the `/plan` dry-run preview.
- `core/state.py` singletons (`TODO`, `SKILLS`, `TASK_MGR`, `BG`, `BUS`) —
  extend with `STATS`, `LSP`, `MCP`; do not introduce new globals.
- `session_tui/widgets.py::LivePanel[T]` — base for any new panel (teammate
  log, task board UI, MCP server status).
- `core/unit/team/messaging.py::MessageBus` — the only inter-agent channel;
  do not introduce a parallel one for MCP.

## What we will *not* do this quarter

- **Trading-specific tools** — domain stays as one example skill bundle, not
  the focus.
- **Web frontend / Cursor-style GUI** — out of scope; revisit after v0.2.
- **Removing persistent teammates / task board** — keep the unique
  differentiator; just don't let it block parity work.
- **OpenAI / Gemini / Bedrock providers** — defer; the two-provider
  abstraction is already a forcing function, three would be premature.

## Verification

For each milestone exit:

1. **`pytest`** must pass with target coverage (60% / 70% / 75% by end of
   M1 / M2 / M3).
2. **`ruff check . && pyright`** must be clean on `src/`.
3. **CI green** on three Python versions × two OSes.
4. **Manual smoke flow** (documented in `docs/QA.md`): launch TUI → `/help` →
   ask agent to read a file, grep, edit a file, run bash → `/compact` →
   spawn teammate → assign task → quit cleanly.
5. **Security checks**: try to read `/etc/passwd` via `read_file`, expect
   deny; pipe a fake API key through bash output, expect redacted log.
6. **Cost / streaming visible** in the stats row.

For M3 specifically:

- `pip install rich-senpai` in a fresh venv, run `rich-senpai`, complete the
  smoke flow against a real Anthropic key.
- Browse the docs site, follow the Quickstart from scratch.
