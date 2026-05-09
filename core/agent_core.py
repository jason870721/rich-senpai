"""Agent core — one ReAct loop per user turn.

`AgentCore.run_turn(messages, user_input)` mutates the supplied message
list in place and returns a `CycleResult`. On the first call (empty
messages) the user input is wrapped with the short-memory scratchpad;
later calls just append it raw so prior turns stay in context.

The loop, per iteration:

  1. Compaction — `microcompact` collapses old tool results, then
     `auto_compact` (LLM-summarised) fires if the budget is blown.
  2. Drain hooks — pending background-task results and inbox messages
     are appended as user turns so the model sees them next call.
  3. LLM call — every registered tool is exposed via `tools.tool_register`.
  4. Tool dispatch — special tools are intercepted (`wait` sleeps and
     re-iterates; `compress` triggers `auto_compact`); everything else
     goes through `tool_register.call_tool`.

Stops when the model returns without tool_use, or when `max_iterations`
is reached. Stateful managers (todos, background, inbox, skills, tasks,
team) live as singletons in `core.state` so tools, the loop, and the
TUI all share one view.

LLM access is provider-neutral: any `core.llm.LLMClient` implementation
can be injected via the `llm` argument; the default is built from
`core.config.LLM_PROVIDER`.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import tiktoken

from core import state
from core.compaction import (
    auto_compact,
    estimate_tokens,
    microcompact,
)
from core.config import (
    MAX_ITERATIONS,
    MAX_TOKENS_PER_CALL,
    SHORT_MEMORY_PATH,
    SHORT_MEMORY_TOKEN_BUDGET,
    TODO_NAG_AFTER_ROUNDS,
    TOKEN_THRESHOLD,
    WAIT_DEFAULT_SECONDS,
    WAIT_MAX_SECONDS,
)
from core.llm import (
    LLMClient,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    build_default_client,
)
from core.sys_prompt import SYSTEM_PROMPT
from tools import tool_register


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
        short_memory_path: str | None = None,
        short_memory_token_budget: int = SHORT_MEMORY_TOKEN_BUDGET,
        max_iterations: int = MAX_ITERATIONS,
        max_tokens_per_call: int = MAX_TOKENS_PER_CALL,
        llm: LLMClient | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        token_threshold: int = TOKEN_THRESHOLD,
    ) -> None:

        self.system_prompt = system_prompt
        self.short_memory_path = short_memory_path or SHORT_MEMORY_PATH
        self.short_memory_token_budget = short_memory_token_budget
        self.max_iterations = max_iterations
        self.max_tokens_per_call = max_tokens_per_call
        self.llm = llm or build_default_client()
        # Share the same LLM with subagent / teammate calls.
        state.set_llm(self.llm)
        self.on_event = on_event
        self.token_threshold = token_threshold
        self._rounds_without_todo = 0
        # Cooperative cancel — set from the UI thread (esc to interrupt),
        # checked at each ReAct iteration boundary. We can't preempt the
        # in-flight LLM HTTP call, but we can short-circuit before the
        # next one or before tool dispatch.
        self._interrupt = threading.Event()

    def close(self) -> None:
        pass

    def request_interrupt(self) -> None:
        """Signal that the current run_turn should stop at the next safe
        boundary. Idempotent; cleared automatically when run_turn starts."""
        self._interrupt.set()

    def _emit(self, event: dict[str, Any]) -> None:
        """Forward a structured event to the on_event callback if set,
        otherwise fall back to the original print() formatting so callers
        that don't pass on_event see identical output."""
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
        self._emit({"type": "inbox_drain", "messages": inbox})

    def _maybe_auto_compact(self, messages: list[Message]) -> None:
        if estimate_tokens(messages) <= self.token_threshold:
            return
        self._emit({"type": "compact", "reason": "auto threshold"})
        messages[:] = auto_compact(messages, llm=self.llm, system=self.system_prompt)

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

    def run_turn(
        self,
        messages: list[Message],
        user_input: str,
    ) -> CycleResult:
        """Run one ReAct loop on a persistent messages list. Mutates in place.

        First turn (empty list): user_input is wrapped with short memory and
        market-state framing via _build_initial_user_message. Subsequent
        turns: user_input is appended raw so prior conversation context is
        preserved across cycles. No audit logging — callers wanting durable
        per-turn rows should use run_cycle instead.
        """

        # if user input is start with "/{skill-name}"
        user_input = self._maybe_add_load_skill_prompt(user_input)

        # Reset cancel state — a new turn always starts uninterrupted.
        # request_interrupt() flipped between turns is intentionally ignored.
        self._interrupt.clear()

        if not messages:
            initial = self._build_initial_user_message(user_input)
            messages.append(Message(role="user", content=[TextBlock(text=initial)]))
        else:
            messages.append(Message(role="user", content=[TextBlock(text=user_input)]))

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

            microcompact(messages, keep_recent=1)
            self._maybe_auto_compact(messages)
            self._drain_background(messages)
            self._drain_inbox(messages)

            # Tell the UI we're about to block on the model so the spinner can
            # flip away from the previous event ("got tool result", etc.).
            self._emit({"type": "llm_request", "iteration": i})
            response = self.llm.create_message(
                messages=messages,
                system=self.system_prompt,
                tools=tool_register.TOOL_SPECS,
                max_tokens=self.max_tokens_per_call,
            )

            # Interrupt requested while the LLM was generating? Skip tool
            # dispatch — the user wanted us to stop, not run more side effects.
            if self._interrupt.is_set():
                self._emit({"type": "interrupted", "iteration": i, "stage": "pre_tool_dispatch"})
                return self._result(
                    final_text_parts, "interrupted", i + 1, tool_calls, total_in, total_out
                )

            self._emit({"type": "llm_response", "iteration": i})

            total_in += response.usage.input_tokens
            total_out += response.usage.output_tokens

            iter_text_parts: list[str] = []
            for block in response.content:
                if isinstance(block, TextBlock):
                    iter_text_parts.append(block.text)
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

            tool_results, sentinel, used_todo = self._dispatch_tool_uses(
                response.content, i, tool_calls
            )

            self._maybe_append_todo_nag(tool_results, used_todo)

            messages.append(Message(role="user", content=list(tool_results)))

            if sentinel == "compress":
                self._emit({"type": "compact", "reason": "manual via compress tool"})
                messages[:] = auto_compact(messages, llm=self.llm, system=self.system_prompt)

        return self._result(
            final_text_parts,
            "max_iterations",
            self.max_iterations,
            tool_calls,
            total_in,
            total_out,
        )

    # ----- internals ---------------------------------------------------------

    def _dispatch_tool_uses(
        self,
        blocks: list[Any],
        iteration: int,
        tool_calls: list[ToolCall],
    ) -> tuple[list[ToolResultBlock], str | None, bool]:
        """Run every tool_use block in `blocks`.

        Returns ``(results, sentinel, used_todo)`` where ``sentinel`` is
        ``"compress"`` if that tool was called this turn (the caller
        runs auto_compact after the user-turn ack) and ``None``
        otherwise. ``wait`` is handled inline — it sleeps in this thread
        and emits a synthetic tool_result — and never sets a sentinel.
        """
        results: list[ToolResultBlock] = []
        sentinel: str | None = None
        used_todo = False

        for block in blocks:
            if not isinstance(block, ToolUseBlock):
                continue
            tool_input = dict(block.input) if block.input else {}

            if block.name == "wait":
                self._handle_wait(block, tool_input, iteration, tool_calls, results)
                continue

            self._emit({
                "type": "tool_use",
                "iteration": iteration,
                "id": block.id,
                "name": block.name,
                "input": tool_input,
            })

            if block.name == "compress":
                output = "compressing conversation context..."
                sentinel = "compress"
            else:
                output = tool_register.call_tool(block.name, tool_input)

            self._emit({
                "type": "tool_result",
                "iteration": iteration,
                "id": block.id,
                "name": block.name,
                "output": output,
            })
            tool_calls.append(ToolCall(block.name, tool_input, output))
            results.append(ToolResultBlock(tool_use_id=block.id, content=output))

            if block.name == "TodoWrite":
                used_todo = True

        return results, sentinel, used_todo

    def _handle_wait(
        self,
        block: ToolUseBlock,
        tool_input: dict[str, Any],
        iteration: int,
        tool_calls: list[ToolCall],
        results: list[ToolResultBlock],
    ) -> None:
        """Sleep for the requested duration, then emit a synthetic
        tool_result so the next iteration's pre-LLM hooks (background /
        inbox drain) get a chance to land fresh data."""
        seconds = _coerce_seconds(tool_input.get("seconds"))
        self._emit({
            "type": "wait",
            "iteration": iteration,
            "id": block.id,
            "seconds": seconds,
        })
        time.sleep(seconds)
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
        short_mem_text = self._read_short_memory()
        parts: list[str] = []

        if short_mem_text:
            token_count = _count_tokens(short_mem_text)
            if token_count > self.short_memory_token_budget:
                parts.append(
                    f"[BUDGET WARNING] Your short memory is at {token_count} "
                    f"tokens, over the {self.short_memory_token_budget} "
                    f"budget. Summarize it via update_short_memory this cycle "
                    f"before doing anything else."
                )
                parts.append("")

        parts.append("# SHORT MEMORY (your scratchpad from the last cycle)")
        parts.append(short_mem_text if short_mem_text else "(empty — first cycle)")
        parts.append("")
        parts.append("# User input:")
        parts.append(user_input)

        return "\n".join(parts)

    def _read_short_memory(self) -> str:
        path = Path(self.short_memory_path)
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"[warn] could not read {path}: {exc}")
            return ""

    @staticmethod
    def _result(
        final_text_parts: list[str],
        stop_reason: str,
        iterations: int,
        tool_calls: list[ToolCall],
        total_in: int,
        total_out: int,
    ) -> CycleResult:
        return CycleResult(
            final_text="\n".join(final_text_parts),
            stop_reason=stop_reason,
            iterations=iterations,
            tool_calls=tool_calls,
            usage={"input_tokens": total_in, "output_tokens": total_out},
        )
