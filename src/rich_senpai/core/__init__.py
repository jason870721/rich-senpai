"""rich-senpai agent core.

Intentionally minimal — importing this package must not eagerly pull in
the agent loop, because tool modules (e.g. tools.shell.background_run)
read `from rich_senpai.core import state` / `core.config` at module top
level and the tool registry then iterates back over those tool modules
to read their SPEC dicts. Eager agent imports here would create a cycle.

Consumers should import `AgentCore`, `CycleResult`, `ToolCall` from
`rich_senpai.core.unit.agent` directly.
"""
