"""Agent core — one async ReAct loop per user turn.

`AgentCore.run_turn(messages, user_input)` is a coroutine that mutates
the supplied message list in place and returns a `CycleResult`. On the
first call (empty messages) the user input is wrapped with the
short-memory scratchpad; later calls just append it raw so prior turns
stay in context.

The loop, per iteration:

  1. Compaction — `microcompact` collapses old tool results, then
     `auto_compact` (LLM-summarised) fires if the budget is blown.
  2. Drain hooks — pending background-task results and inbox messages
     are appended as user turns so the model sees them next call.
  3. LLM call — every registered tool is exposed via `tools.tool_register`.
     The call is awaited as a tracked `asyncio.Task` so
     `request_interrupt()` can cancel the in-flight HTTP request rather
     than waiting for the model to finish generating.
  4. Tool dispatch — special tools are intercepted (`wait` sleeps via
     a cancellable `asyncio.sleep` and re-iterates; `compress` triggers
     `auto_compact`); everything else goes through `tool_register.call_tool`,
     which awaits async handlers directly and runs sync handlers on a
     worker thread.

Stops when the model returns without tool_use, when `max_iterations`
is reached, or when interrupted (LLM call cancelled, or `_interrupt`
flag observed at an iteration boundary). Stateful managers (todos,
background, inbox, skills, tasks, team) live as singletons in
`core.state` so tools, the loop, and the TUI all share one view.

LLM access is provider-neutral: any `core.llm.LLMClient` implementation
can be injected via the `llm` argument; the default is built from
`core.config.LLM_PROVIDER`.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import tiktoken

from rich_senpai.core import state
from rich_senpai.core.unit.agent.compaction import (
    auto_compact,
    estimate_tokens,
    microcompact,
)
from rich_senpai.core.config import (
    MAX_ITERATIONS,
    MAX_TOKENS_PER_CALL,
    MICROCOMPACT_KEEP_RECENT,
    MICROCOMPACT_MIN_KEEP_RECENT,
    TODO_NAG_AFTER_ROUNDS,
    TOKEN_THRESHOLD,
    WAIT_DEFAULT_SECONDS,
    WAIT_MAX_SECONDS,
)
from rich_senpai.core.llm import (
    LLMClient,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    build_default_client,
)
from rich_senpai.core.logging_setup import clip, get_logger
from rich_senpai.core.unit.agent.sys_prompt import SYSTEM_PROMPT
from rich_senpai.tools import tool_register


log = get_logger(__name__)


_TIKTOKEN_ENCODER = tiktoken.get_encoding("cl100k_base")


def _count_tokens(text: str) -> int:
    return len(_TIKTOKEN_ENCODER.encode(text))


def _coerce_seconds(raw: Any) -> int:
    """Validate a ``wait``-tool ``seconds`` argument.

    Falls back to the configured default for unparsable input and clamps
    the result to ``[1, WAIT_MAX_SECONDS]``.
    """
    try:
        seconds = int(raw) if raw is not None else WAIT_DEFAULT_SECONDS
    except (TypeError, ValueError):
        seconds = WAIT_DEFAULT_SECONDS
    return max(1, min(seconds, WAIT_MAX_SECONDS))


@dataclass
class ToolCall:
    name: str
    input: dict[str, Any]
    output: str


@dataclass
class CycleResult:
    final_text: str
    stop_reason: str
    iterations: int
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)


class AgentCore:
    def __init__(
        self,
        *,
        system_prompt: str = SYSTEM_PROMPT,
        max_iterations: int = MAX_ITERATIONS,
        max_tokens_per_call: int = MAX_TOKENS_PER_CALL,
        llm: LLMClient | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        token_threshold: int = TOKEN_THRESHOLD,
        keep_recent: int = MICROCOMPACT_KEEP_RECENT,
    ) -> None:

        if keep_recent < MICROCOMPACT_MIN_KEEP_RECENT:
            raise ValueError(
                f"keep_recent must be >= {MICROCOMPACT_MIN_KEEP_RECENT} "
                f"so all progressive compaction tiers are exercised "
                f"(got {keep_recent})"
            )
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.max_tokens_per_call = max_tokens_per_call
        self.keep_recent = keep_recent
        self.llm = llm or build_default_client()
        # Share the same LLM with subagent / teammate calls.
        state.set_llm(self.llm)
        self.on_event = on_event
        self.token_threshold = token_threshold
        self._rounds_without_todo = 0
        # Per-instance recovery map for microcompact. Key: tool_use_id,
        # value: full original tool_result content. Populated lazily the
        # first time a result is compacted; consulted by the intercepted
        # `recover_compacted_tool_use_result` tool. Cleared after every
        # auto_compact (since the new summary message has no tool_use_ids
        # tying back to the old entries) and on /clear in the TUI.
        self._recovery_map: dict[str, str] = {}
        # One-shot flag for `_reach_max_iter_count_prompt` so the wrap-up
        # reminder gets injected exactly once per run_turn even though the
        # threshold check fires on both the second-to-last and last
        # iterations. Reset at the top of every run_turn.
        self._max_iter_warned = False
        # Cooperative cancel — set from the UI when the user hits Esc.
        # Checked at iteration boundaries so we bail out cleanly between
        # ReAct steps even when no async op is currently in flight.
        self._interrupt = asyncio.Event()
        # Whatever cancellable async op is currently in flight (LLM call
        # or `wait` sleep). `request_interrupt` cancels this task so the
        # HTTP request / sleep aborts mid-flight rather than running to
        # completion.
        self._current_task: asyncio.Task[Any] | None = None

    def close(self) -> None:
        pass

    def request_interrupt(self) -> None:
        """Signal that the current run_turn should stop. Cancels the
        in-flight LLM call (or `wait` sleep) so the HTTP request aborts
        mid-generation; otherwise observed at the next ReAct iteration
        boundary. Idempotent; cleared automatically when run_turn starts."""
        self._interrupt.set()
        task = self._current_task
        if task is not None and not task.done():
            task.cancel()

    def _emit(self, event: dict[str, Any]) -> None:
        """Forward a structured event to the on_event callback if set,
        otherwise fall back to the original print() formatting so callers
        that don't pass on_event see identical output."""
        # this on event will send event to tui (display).
        if self.on_event is not None:
            self.on_event(event)
            return
        kind = event.get("type")
        i = event.get("iteration", 0)
        if kind == "assistant_text":
            print(f"[assistant {i}]\n{event['text']}\n")
        elif kind == "tool_use":
            print(f"[tool_use {i}] {event['name']}({event['input']})")
        elif kind == "tool_result":
            print(f"[tool_result {i}]\n{event['output']}\n")
        elif kind == "wait":
            print(f"[wait] iteration {i}, sleeping {event.get('seconds', '?')}s")
        elif kind == "compact":
            print(f"[compact] {event.get('reason', '')}")
        elif kind == "background_drain":
            print(f"[background] {len(event['notifications'])} notification(s)")
        elif kind == "inbox_drain":
            print(f"[inbox] {len(event['messages'])} message(s)")

    # ----- pre-LLM hooks -----------------------------------------------------

    def _drain_background(self, messages: list[Message]) -> None:
        notifs = state.BG.drain()
        if not notifs:
            return
        text = "\n".join(
            f"[bg:{n['task_id']}] {n['status']}: {n['result']}" for n in notifs
        )
        messages.append(
            Message(
                role="user",
                content=[TextBlock(text=f"<background-results>\n{text}\n</background-results>")],
            )
        )
        log.info("background_drain notifications=%d", len(notifs))
        log.debug("background_drain payload=%s", clip(text))
        self._emit({"type": "background_drain", "notifications": notifs})

    def _drain_inbox(self, messages: list[Message]) -> None:
        inbox = state.BUS.read_inbox(state.LEAD_NAME)
        if not inbox:
            return
        messages.append(
            Message(
                role="user",
                content=[TextBlock(text=f"<inbox>{json.dumps(inbox, indent=2)}</inbox>")],
            )
        )
        log.info("inbox_drain messages=%d", len(inbox))
        log.debug("inbox_drain payload=%s", clip(inbox))
        self._reconcile_shutdown_responses(inbox)
        self._emit({"type": "inbox_drain", "messages": inbox})

    def _reconcile_shutdown_responses(self, inbox: list[dict[str, Any]]) -> None:
        """Pop fulfilled shutdown_request entries from the registry as
        their `shutdown_response` messages arrive in the lead's inbox.
        Without this the registry leaks one entry per shutdown_request
        tool call. Inbox JSON is still surfaced to the model verbatim
        — this only manages the lead-side bookkeeping."""
        # Local import — `core.unit.team.messaging` is already imported
        # transitively via `core.state.BUS`; importing here keeps the
        # dependency arrow one-directional and avoids a top-level cycle.
        from rich_senpai.core.unit.team.messaging import shutdown_requests
        for msg in inbox:
            if msg.get("type") != "shutdown_response":
                continue
            req_id = msg.get("request_id")
            if not req_id:
                continue
            entry = shutdown_requests.pop(req_id, None)
            if entry is not None:
                log.info(
                    "shutdown_response acked request_id=%s target=%s sender=%s",
                    req_id,
                    entry.get("target"),
                    msg.get("from"),
                )

    async def _maybe_auto_compact(self, messages: list[Message]) -> None:
        tokens = estimate_tokens(messages)
        if tokens <= self.token_threshold:
            return
        log.info(
            "auto_compact triggered tokens=%d threshold=%d messages=%d",
            tokens,
            self.token_threshold,
            len(messages),
        )
        self._emit({"type": "compact", "reason": "auto threshold"})
        messages[:] = await auto_compact(messages, llm=self.llm, system=self.system_prompt)
        # The summary message that replaces the transcript has no tool_use_ids,
        # so every entry in the recovery map is now unreachable. Drop them
        # so the cap doesn't fill up with dead state.
        self._recovery_map.clear()
        log.info("auto_compact done messages=%d", len(messages))

    def _maybe_add_load_skill_prompt(self, user_input: str) -> str:
        """
        Convert slash-prefixed input into a lightweight instruction
        that tells the model a skill may be relevant.

        The model can decide whether it actually needs to load
        the skill content.
        """

        stripped = user_input.lstrip()

        if not stripped.startswith("/"):
            return user_input

        command, _, rest = stripped[1:].partition(" ")

        skill_name = command.strip()

        if not skill_name:
            return user_input

        skill = state.SKILLS.skills.get(skill_name)

        if skill is None:
            return user_input

        description = skill["description"]

        guidance = (
            f"The user referenced skill '{skill_name}'.\n"
            f"Skill description: {description}\n\n"
            f"If the exact skill content is already known from prior context, "
            f"respond normally.\n"
            f"Otherwise, use the load_skill tool to retrieve the full skill content."
        )

        if rest.strip():
            return f"{guidance}\n\nUser request:\n{rest.strip()}"

        return guidance

    # ----- public API --------------------------------------------------------

    async def run_turn(
        self,
        messages: list[Message],
        user_input: str,
    ) -> CycleResult:
        """Run one async ReAct loop on a persistent messages list.

        First turn (empty list): user_input is wrapped with short memory
        and market-state framing via _build_initial_user_message.
        Subsequent turns: user_input is appended raw so prior conversation
        context is preserved across cycles. Mutates `messages` in place.
        """

        # if user input is start with "/{skill-name}"
        user_input = self._maybe_add_load_skill_prompt(user_input)

        self._reset_turn_state()

        log.info(
            "run_turn start prior_messages=%d input_chars=%d max_iterations=%d",
            len(messages),
            len(user_input),
            self.max_iterations,
        )
        log.debug("user_input=%s", clip(user_input))

        if not messages:
            initial = self._build_initial_user_message(user_input)
            messages.append(Message(role="user", content=[TextBlock(text=initial)]))
        else:
            messages.append(Message(role="user", content=[TextBlock(text=user_input)]))

        return await self._run_loop(messages)

    async def continue_run(self, messages: list[Message]) -> CycleResult:
        """Re-enter the ReAct loop on an existing message list without
        appending a fresh user turn.

        Called by the TUI after a turn hit ``max_iterations`` and the user
        pressed Enter to keep going. The iteration counter restarts from
        0, the interrupt flag is cleared, and the wrap-up reminder will
        fire again toward the new budget's end. Mutates ``messages`` in
        place just like ``run_turn``.
        """
        self._reset_turn_state()
        log.info(
            "continue_run start prior_messages=%d max_iterations=%d",
            len(messages),
            self.max_iterations,
        )
        return await self._run_loop(messages)

    def _reset_turn_state(self) -> None:
        """Clear per-turn flags shared by ``run_turn`` / ``continue_run``.

        Idempotent — the interrupt flag is cleared, the cancellable-task
        handle dropped, and the one-shot max-iter warning re-armed so the
        new budget gets its own wrap-up nudge.
        """
        # Reset cancel state — a new turn always starts uninterrupted.
        # request_interrupt() flipped between turns is intentionally ignored.
        self._interrupt.clear()
        self._current_task = None
        self._max_iter_warned = False

    async def _run_loop(self, messages: list[Message]) -> CycleResult:
        """Run the ReAct loop on ``messages`` for up to ``max_iterations``.

        Shared body of ``run_turn`` and ``continue_run`` — neither
        modifies ``messages`` before this point beyond appending the
        user's new turn (run_turn) or nothing at all (continue_run).
        """
        tool_calls: list[ToolCall] = []
        final_text_parts: list[str] = []
        total_in = 0
        total_out = 0

        for i in range(self.max_iterations):
            if self._interrupt.is_set():
                self._emit({"type": "interrupted", "iteration": i, "stage": "pre_iteration"})
                return self._result(
                    final_text_parts, "interrupted", i, tool_calls, total_in, total_out
                )

            # Cadence: fire microcompact every `keep_recent` iterations
            # (so iter 0 of every run_turn/continue_run always compacts,
            # then iter keep_recent, 2*keep_recent, …). The recovery map
            # carries originals so re-tiering uses fresh percentages off
            # the unmodified content.
            if i % self.keep_recent == 0:
                microcompact(
                    messages,
                    recovery_map=self._recovery_map,
                    keep_recent=self.keep_recent,
                )
            await self._maybe_auto_compact(messages)
            self._drain_background(messages)
            self._drain_inbox(messages)
            self._reach_max_iter_count_prompt(i+1, messages)

            # Tell the UI we're about to block on the model so the spinner can
            # flip away from the previous event ("got tool result", etc.).
            self._emit({"type": "llm_request", "iteration": i})
            log.info(
                "iteration=%d llm_request messages=%d tools=%d max_tokens=%d",
                i,
                len(messages),
                len(tool_register.TOOL_SPECS),
                self.max_tokens_per_call,
            )
            log.debug(
                "iteration=%d llm_request payload last_message=%s",
                i,
                clip(_summarise_message(messages[-1])) if messages else "<none>",
            )
            try:
                response = await self._await_llm(
                    messages=messages,
                    system=self.system_prompt,
                    tools=tool_register.TOOL_SPECS,
                    max_tokens=self.max_tokens_per_call,
                )
            except asyncio.CancelledError:
                if self._interrupt.is_set():
                    self._emit({"type": "interrupted", "iteration": i, "stage": "llm_call"})
                    return self._result(
                        final_text_parts, "interrupted", i + 1, tool_calls, total_in, total_out
                    )
                # Cancellation we didn't initiate (e.g. worker teardown)
                # — let it propagate so callers can clean up.
                raise

            # Interrupt requested between LLM response and tool dispatch?
            # Skip dispatch — the user wanted us to stop, not run more
            # side effects. Drop the assistant turn entirely so the
            # message list stays valid (no orphan tool_use without
            # matching tool_result).
            if self._interrupt.is_set():
                self._emit({"type": "interrupted", "iteration": i, "stage": "pre_tool_dispatch"})
                return self._result(
                    final_text_parts, "interrupted", i + 1, tool_calls, total_in, total_out
                )

            self._emit({"type": "llm_response", "iteration": i})

            total_in += response.usage.input_tokens
            total_out += response.usage.output_tokens

            text_blocks = sum(1 for b in response.content if isinstance(b, TextBlock))
            tool_blocks = sum(1 for b in response.content if isinstance(b, ToolUseBlock))
            log.info(
                "iteration=%d llm_response stop=%s in=%d out=%d text_blocks=%d tool_uses=%d",
                i,
                response.stop_reason,
                response.usage.input_tokens,
                response.usage.output_tokens,
                text_blocks,
                tool_blocks,
            )

            iter_text_parts: list[str] = []
            for block in response.content:
                if isinstance(block, TextBlock):
                    iter_text_parts.append(block.text)
                    log.debug("iteration=%d assistant_text=%s", i, clip(block.text))
                    self._emit({"type": "assistant_text", "iteration": i, "text": block.text})
            if iter_text_parts:
                final_text_parts = iter_text_parts

            messages.append(Message(role="assistant", content=list(response.content)))

            if response.stop_reason != "tool_use":
                return self._result(
                    final_text_parts,
                    response.stop_reason or "end_turn",
                    i + 1,
                    tool_calls,
                    total_in,
                    total_out,
                )

            tool_results, sentinel, used_todo = await self._dispatch_tool_uses(
                response.content, i, tool_calls
            )

            self._maybe_append_todo_nag(tool_results, used_todo)

            messages.append(Message(role="user", content=list(tool_results)))

            if sentinel == "compress":
                self._emit({"type": "compact", "reason": "manual via compress tool"})
                messages[:] = await auto_compact(messages, llm=self.llm, system=self.system_prompt)

        self._emit({"type": "max_iter_pause", "iterations": self.max_iterations})
        return self._result(
            final_text_parts,
            "max_iterations",
            self.max_iterations,
            tool_calls,
            total_in,
            total_out,
        )

    # ----- internals ---------------------------------------------------------

    async def _await_llm(
        self,
        *,
        messages: list[Message],
        system: str,
        tools: list[dict[str, Any]],
        max_tokens: int,
    ):
        """Issue an LLM call as a tracked Task so request_interrupt can
        cancel the in-flight HTTP request mid-generation. Returns the
        provider's `LLMResponse`."""
        task = asyncio.create_task(
            self.llm.create_message(
                messages=messages,
                system=system,
                tools=tools,
                max_tokens=max_tokens,
            )
        )
        self._current_task = task
        try:
            return await task
        finally:
            self._current_task = None

    async def _dispatch_tool_uses(
        self,
        blocks: list[Any],
        iteration: int,
        tool_calls: list[ToolCall],
    ) -> tuple[list[ToolResultBlock], str | None, bool]:
        """Run every tool_use block in `blocks`.

        Returns ``(results, sentinel, used_todo)`` where ``sentinel`` is
        ``"compress"`` if that tool was called this turn (the caller
        runs auto_compact after the user-turn ack) and ``None``
        otherwise. ``wait`` is handled inline — it sleeps via a
        cancellable `asyncio.sleep` and emits a synthetic tool_result —
        and never sets a sentinel.
        """
        results: list[ToolResultBlock] = []
        sentinel: str | None = None
        used_todo = False

        for block in blocks:
            if not isinstance(block, ToolUseBlock):
                continue
            tool_input = dict(block.input) if block.input else {}

            if block.name == "wait":
                await self._handle_wait(block, tool_input, iteration, tool_calls, results)
                continue

            self._emit({
                "type": "tool_use",
                "iteration": iteration,
                "id": block.id,
                "name": block.name,
                "input": tool_input,
            })
            log.info(
                "iteration=%d tool_use id=%s name=%s",
                iteration,
                block.id,
                block.name,
            )
            log.debug(
                "iteration=%d tool_use id=%s name=%s input=%s",
                iteration,
                block.id,
                block.name,
                clip(tool_input),
            )

            if block.name == "compress":
                tool_result = tool_register.ToolResult(
                    text="compressing conversation context...", ok=True
                )
                sentinel = "compress"
            elif block.name == "recover_compacted_tool_use_result":
                tool_result = self._handle_recover(tool_input)
            else:
                tool_result = await tool_register.call_tool(block.name, tool_input)

            self._emit({
                "type": "tool_result",
                "iteration": iteration,
                "id": block.id,
                "name": block.name,
                "output": tool_result.text,
                "ok": tool_result.ok,
            })
            log.info(
                "iteration=%d tool_result id=%s name=%s ok=%s output_chars=%d",
                iteration,
                block.id,
                block.name,
                tool_result.ok,
                len(tool_result.text),
            )
            log.debug(
                "iteration=%d tool_result id=%s name=%s output=%s",
                iteration,
                block.id,
                block.name,
                clip(tool_result.text),
            )
            tool_calls.append(ToolCall(block.name, tool_input, tool_result.text))
            results.append(ToolResultBlock(tool_use_id=block.id, content=tool_result.text))

            if block.name == "TodoWrite":
                used_todo = True

        return results, sentinel, used_todo

    def _handle_recover(self, tool_input: dict[str, Any]) -> tool_register.ToolResult:
        """Look up the requested ``tool_use_id`` in the per-instance
        recovery map and return its full original content.

        Intercepted in ``_dispatch_tool_uses`` rather than dispatched
        through the registry because the map lives on the AgentCore
        instance — the module-level handler in
        ``tools/memory/recover_compacted_tool_use_result.py`` cannot
        reach it and only exists so the tool registers cleanly.
        """
        tool_use_id = tool_input.get("tool_use_id")
        if not isinstance(tool_use_id, str) or not tool_use_id:
            return tool_register.ToolResult(
                text="error: 'tool_use_id' is required and must be a non-empty string.",
                ok=False,
            )
        original = self._recovery_map.get(tool_use_id)
        if original is None:
            return tool_register.ToolResult(
                text=(
                    f"error: no original content for tool_use_id={tool_use_id!r}. "
                    "It was never compacted, the id is wrong, or auto_compact "
                    "cleared the recovery map. Check the stub for the exact id."
                ),
                ok=False,
            )
        return tool_register.ToolResult(text=original, ok=True)

    async def _handle_wait(
        self,
        block: ToolUseBlock,
        tool_input: dict[str, Any],
        iteration: int,
        tool_calls: list[ToolCall],
        results: list[ToolResultBlock],
    ) -> None:
        """Sleep for the requested duration via a tracked
        `asyncio.sleep`, then emit a synthetic tool_result so the next
        iteration's pre-LLM hooks (background / inbox drain) get a
        chance to land fresh data.

        If `request_interrupt` cancels the sleep mid-flight, we emit a
        "wait cancelled" tool_result and let the loop continue — the
        pre-iteration check on the next pass observes `_interrupt` and
        bails cleanly with valid conversation state.
        """
        seconds = _coerce_seconds(tool_input.get("seconds"))
        log.info("iteration=%d wait id=%s seconds=%d", iteration, block.id, seconds)
        self._emit({
            "type": "wait",
            "iteration": iteration,
            "id": block.id,
            "seconds": seconds,
        })
        sleep_task = asyncio.create_task(asyncio.sleep(seconds))
        self._current_task = sleep_task
        interrupted_mid_sleep = False
        try:
            await sleep_task
        except asyncio.CancelledError:
            if not self._interrupt.is_set():
                raise
            interrupted_mid_sleep = True
        finally:
            self._current_task = None

        if interrupted_mid_sleep:
            output = (
                f"wait cancelled by user before {seconds}s elapsed; "
                f"the agent will stop at the next iteration boundary."
            )
        else:
            output = (
                f"slept {seconds}s — re-iterating; pre-LLM hooks will drain "
                f"background results / inbox before the next call."
            )
        self._emit({
            "type": "tool_result",
            "iteration": iteration,
            "id": block.id,
            "name": "wait",
            "output": output,
            "ok": True,
        })
        tool_calls.append(ToolCall(block.name, tool_input, output))
        results.append(ToolResultBlock(tool_use_id=block.id, content=output))

    def _maybe_append_todo_nag(
        self,
        results: list[Any],
        used_todo: bool,
    ) -> None:
        if used_todo:
            self._rounds_without_todo = 0
            return
        self._rounds_without_todo += 1
        if (
            state.TODO.has_open_items()
            and self._rounds_without_todo >= TODO_NAG_AFTER_ROUNDS
        ):
            # Append as plain text alongside the tool_results — mixing is allowed
            # in user turns and avoids fabricating a tool_use_id.
            results.append(TextBlock(text="<reminder>Update your todos with TodoWrite tool.</reminder>"))

    def _build_initial_user_message(self, user_input: str) -> str:
        parts: list[str] = []
        parts.append("")
        parts.append("# User input:")
        parts.append(user_input)

        return "\n".join(parts)

    @staticmethod
    def _result(
        final_text_parts: list[str],
        stop_reason: str,
        iterations: int,
        tool_calls: list[ToolCall],
        total_in: int,
        total_out: int,
    ) -> CycleResult:
        result = CycleResult(
            final_text="\n".join(final_text_parts),
            stop_reason=stop_reason,
            iterations=iterations,
            tool_calls=tool_calls,
            usage={"input_tokens": total_in, "output_tokens": total_out},
        )
        log.info(
            "run_turn end stop=%s iterations=%d tool_calls=%d in=%d out=%d final_chars=%d",
            stop_reason,
            iterations,
            len(tool_calls),
            total_in,
            total_out,
            len(result.final_text),
        )
        return result

    def _reach_max_iter_count_prompt(
        self,
        iter_count: int,
        messages: list[Message],
    ) -> None:
        """Inject a one-shot wrap-up reminder when the iteration budget is
        almost gone.

        Fires exactly once per run_turn, on the second-to-last iteration,
        so the model still has one more LLM call to deliver a final reply
        before the loop exits with stop="max_iterations". The reminder
        rides on a synthetic user turn — same shape `_drain_background`
        / `_drain_inbox` use — so it lands on the next LLM call alongside
        any drained tool_results.

        ``iter_count`` is 1-indexed (the iteration about to start). With
        max_iterations=40 the threshold fires at iter_count=39 (one more
        LLM call after this one) and the idempotent guard skips the
        repeat at iter_count=40.
        """
        if self._max_iter_warned:
            return
        remaining = self.max_iterations - iter_count
        if remaining > 1:
            return
        self._max_iter_warned = True
        reminder = (
            "<reminder>"
            f"Iteration budget almost exhausted: {remaining} iteration(s) "
            f"remain before max_iterations ({self.max_iterations}) forces a "
            "stop. Do NOT start new tool calls. Use your next reply to "
            "deliver the final answer to the user. If the work is "
            "unfinished, the reply MUST include: "
            "(1) what you completed this turn, "
            "(2) what is still pending, "
            "(3) any blockers the user must resolve before the next turn. "
            "Be concrete — name files, functions, or data the user can "
            "pick up from."
            "</reminder>"
        )
        messages.append(
            Message(role="user", content=[TextBlock(text=reminder)])
        )
        log.info(
            "max_iter wrap-up reminder injected iter=%d/%d remaining=%d",
            iter_count,
            self.max_iterations,
            remaining,
        )



def _summarise_message(message: Message) -> str:
    """Compact summary of a Message for DEBUG logs — role + per-block hint."""
    parts: list[str] = []
    for block in message.content:
        if isinstance(block, TextBlock):
            parts.append(f"text({len(block.text)}c)")
        elif isinstance(block, ToolUseBlock):
            parts.append(f"tool_use({block.name})")
        elif isinstance(block, ToolResultBlock):
            content = block.content
            length = len(content) if isinstance(content, str) else len(repr(content))
            parts.append(f"tool_result({length}c)")
        else:
            parts.append(type(block).__name__)
    return f"{message.role}[{', '.join(parts)}]"
