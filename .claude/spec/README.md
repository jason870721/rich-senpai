# `.claude/spec/`

Per-module development specs and progress trackers, owned by Claude Code.

Each subdirectory is one module. Inside each module folder:

- `SPEC.md` — what the module is, its boundaries, public interface, design decisions.
- `PLAN.md` — phased implementation plan with concrete milestones.
- `PROGRESS.md` — what is done, in flight, and blocked. Update at the end of each working session.

## Modules

- [`agent-core/`](./agent-core/) — the ReAct loop, LLM client wrapper, and tool dispatch glue. Owner of `core/agent_core.py`.
