# register all agent tool here
from typing import Any, Callable

from tools import (
    background_run,
    bash,
    broadcast,
    check_background,
    claim_task,
    compress,
    edit_file,
    http_request,
    idle,
    list_teammates,
    load_skill,
    plan_approval,
    read_file,
    read_inbox,
    send_message,
    shutdown_request,
    spawn_teammate,
    task,
    task_create,
    task_get,
    task_list,
    task_update,
    todo_write,
    update_short_memory,
    wait,
    write_file,
)


SYS_TOOL_PROMPT = """
You have access to a layered toolset.

# File / shell / data
- read_file: read a local text file.
- write_file: create or overwrite a file (parents created automatically).
- edit_file: replace the first occurrence of old_text with new_text.
- bash: run a shell command. Killed after 30s by default.
- background_run / check_background: launch a long shell job in a thread
  and check on it later. Completion notifications surface automatically
  on the next turn.
- http_request: send an HTTP request and return the response.
- update_short_memory: overwrite short_memory.md (keep under 3000 tokens).

# Working memory
- TodoWrite: short, in-session checklist (capped at 20 items, one in_progress).
- task_create / task_get / task_update / task_list / claim_task: persistent
  file-backed task board, shared with teammates.

# Delegation
- task: spawn a focused subagent for a single self-contained job
  (Explore = read-only; general-purpose = read+write).
- spawn_teammate / list_teammates: start a long-lived autonomous worker
  that runs in its own thread and auto-claims pending tasks while idle.
- send_message / read_inbox / broadcast: lead-side messaging over .team/inbox.
- shutdown_request: ask a teammate to stop cleanly.
- plan_approval: approve or reject a plan a teammate sent for review.

# Context management
- compress: manually trigger an auto-compaction of the conversation.
- wait: end this cycle and sleep until the next tick. Do not call any
  other tool in the same turn as wait.

Pick the narrowest tool that fits. Prefer read_file over bash, edit_file
over write_file for targeted changes, and the persistent task board over
TodoWrite when work needs to outlive the current session. Never run
destructive shell commands without explicit user confirmation.
""".strip()


TOOL_SPECS: list[dict[str, Any]] = [
    # file / shell / data
    read_file.SPEC,
    write_file.SPEC,
    edit_file.SPEC,
    bash.SPEC,
    background_run.SPEC,
    check_background.SPEC,
    http_request.SPEC,
    update_short_memory.SPEC,
    # working memory
    todo_write.SPEC,
    task_create.SPEC,
    task_get.SPEC,
    task_update.SPEC,
    task_list.SPEC,
    claim_task.SPEC,
    # delegation
    task.SPEC,
    spawn_teammate.SPEC,
    list_teammates.SPEC,
    send_message.SPEC,
    read_inbox.SPEC,
    broadcast.SPEC,
    shutdown_request.SPEC,
    plan_approval.SPEC,
    # context management
    load_skill.SPEC,
    compress.SPEC,
    idle.SPEC,
    wait.SPEC,
]

TOOL_HANDLERS: dict[str, Callable[..., str]] = {
    read_file.SPEC["name"]: read_file.read_file,
    write_file.SPEC["name"]: write_file.write_file,
    edit_file.SPEC["name"]: edit_file.edit_file,
    bash.SPEC["name"]: bash.bash,
    background_run.SPEC["name"]: background_run.background_run,
    check_background.SPEC["name"]: check_background.check_background,
    http_request.SPEC["name"]: http_request.http_request,
    update_short_memory.SPEC["name"]: update_short_memory.update_short_memory,
    todo_write.SPEC["name"]: todo_write.todo_write,
    task_create.SPEC["name"]: task_create.task_create,
    task_get.SPEC["name"]: task_get.task_get,
    task_update.SPEC["name"]: task_update.task_update,
    task_list.SPEC["name"]: task_list.task_list,
    claim_task.SPEC["name"]: claim_task.claim_task,
    task.SPEC["name"]: task.task,
    spawn_teammate.SPEC["name"]: spawn_teammate.spawn_teammate,
    list_teammates.SPEC["name"]: list_teammates.list_teammates,
    send_message.SPEC["name"]: send_message.send_message,
    read_inbox.SPEC["name"]: read_inbox.read_inbox,
    broadcast.SPEC["name"]: broadcast.broadcast,
    shutdown_request.SPEC["name"]: shutdown_request.shutdown_request,
    plan_approval.SPEC["name"]: plan_approval.plan_approval,
    load_skill.SPEC["name"]: load_skill.load_skill,
    compress.SPEC["name"]: compress.compress,
    idle.SPEC["name"]: idle.idle,
    wait.SPEC["name"]: wait.wait,
}


def call_tool(name: str, arguments: dict[str, Any] | None = None) -> str:
    """Dispatch a tool call by name. Returns the tool's string output, or an
    error string if the tool name is unknown or arguments are invalid."""
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return f"error: unknown tool '{name}'"
    try:
        return handler(**(arguments or {}))
    except TypeError as exc:
        return f"error: invalid arguments for '{name}': {exc}"
