"""Shell tools — bash, background processes.

This package init is intentionally empty (no eager submodule import).
Eager `from .X import X` here used to create a circular import: pytest
collecting a single `bash` test would load this __init__, which loaded
`background_run`, which imported `core.state` -> agent -> tool_register,
which iterated back over `background_run` *before its SPEC dict had been
defined*. Consumers should import the submodule directly, e.g.
`from rich_senpai.tools.shell import bash` (which Python resolves as the
submodule once this __init__ has no shadowing attribute).
"""
