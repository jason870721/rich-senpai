"""Agent core — Phase 3 ReAct loop with audit logging.

One call to `run_cycle`:

  1. Reads short_memory.md (creates nothing; missing file = empty memory).
  2. Builds the first user message: optional budget warning + memory + market state.
  3. Runs the ReAct loop until the model stops asking for tools, calls the
     synthetic `wait` tool, or `max_iterations` is hit.
  4. On every exit path — clean *or* exceptional — writes one row to
     agent_logs via core.audit.log_cycle.

Phase 4 unifies env-var config; Phase 5 adds retry/backoff and tool-loop guards.
"""
from __future__ import annotations

import os
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import anthropic
import tiktoken

from core import audit
from tools import tool_register


SYSTEM_PROMPT= (
    "You are rich-senpai, an autonomous trading agent (development build).\n"
    "Local tools: read_file, write_file, bash, http_request, "
    "update_short_memory, wait.\n"
    "Persist your thesis and notes via update_short_memory between cycles "
    "(keep it under 3000 tokens — summarize when it grows). "
    "Call exactly one tool per turn. When done with this cycle, call wait."
)

# MODEL_NAME = "claude-sonnet-4-7"
MODEL_NAME = "claude-haiku-4-5-20251001"


_TIKTOKEN_ENCODER = tiktoken.get_encoding("cl100k_base")


def _count_tokens(text: str) -> int:
    return len(_TIKTOKEN_ENCODER.encode(text))


def _micro_compact_tool_results(
    messages: list[dict[str, Any]],
    *,
    keep_recent: int = 1,
    threshold: int = 200,
) -> None:
    """In-place: replace tool_result content in older user turns with a
    compact stub, preserving tool_use_id so the model can still match
    results to calls. Keeps the most recent `keep_recent` tool_result-bearing
    user turns intact. Idempotent — already-compacted stubs (< threshold
    chars) pass through unchanged."""
    indices = [
        i for i, m in enumerate(messages)
        if m.get("role") == "user"
        and isinstance(m.get("content"), list)
        and any(
            isinstance(b, dict) and b.get("type") == "tool_result"
            for b in m["content"]
        )
    ]
    if len(indices) <= keep_recent:
        return

    to_compact = indices[:-keep_recent] if keep_recent > 0 else indices
    for idx in to_compact:
        new_content: list[Any] = []
        for block in messages[idx]["content"]:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_result"
                and isinstance(block.get("content"), str)
                and len(block["content"]) > threshold
            ):
                stub = f"[compacted: {len(block['content'])} chars elided]"
                new_content.append({**block, "content": stub})
            else:
                new_content.append(block)
        messages[idx]["content"] = new_content


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
    ## init core parameters
    def __init__(
        self,
        *,
        model: str = MODEL_NAME,
        system_prompt: str = SYSTEM_PROMPT,
        short_memory_path: str | None = None,
        short_memory_token_budget: int = 3000,
        max_iterations: int = 30,
        max_tokens_per_call: int = 4096,
        client: anthropic.Anthropic | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.model = model
        self.system_prompt = system_prompt
        self.short_memory_path = short_memory_path or os.environ.get(
            "RICH_SENPAI_SHORT_MEM", "short_memory.md"
        )
        self.short_memory_token_budget = short_memory_token_budget
        self.max_iterations = max_iterations
        self.max_tokens_per_call = max_tokens_per_call
        self.client = client or anthropic.Anthropic()
        self.on_event = on_event

    def close(self) -> None:
        pass

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
            print(f"[wait] iteration {i}, exiting cycle")

    def run_turn(
        self,
        messages: list[dict[str, Any]],
        user_input: str,
    ) -> CycleResult:
        """Run one ReAct loop on a persistent messages list. Mutates in place.

        First turn (empty list): user_input is wrapped with short memory and
        market-state framing via _build_initial_user_message. Subsequent
        turns: user_input is appended raw so prior conversation context is
        preserved across cycles. No audit logging — callers wanting durable
        per-turn rows should use run_cycle instead.
        """
        if not messages:
            initial = self._build_initial_user_message(user_input)
            messages.append({"role": "user", "content": initial})
        else:
            messages.append({"role": "user", "content": user_input})

        tool_calls: list[ToolCall] = []
        final_text_parts: list[str] = []
        total_in = 0
        total_out = 0

        for i in range(self.max_iterations):
            _micro_compact_tool_results(messages, keep_recent=1)

            response = self.client.messages.create(
                model=self.model,
                system=self.system_prompt,
                tools=tool_register.TOOL_SPECS,
                messages=messages,
                max_tokens=self.max_tokens_per_call,
            )

            total_in += response.usage.input_tokens
            total_out += response.usage.output_tokens

            iter_text_parts: list[str] = []
            for block in response.content:
                if block.type == "text":
                    iter_text_parts.append(block.text)
                    self._emit({"type": "assistant_text", "iteration": i, "text": block.text})
            if iter_text_parts:
                final_text_parts = iter_text_parts

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                return self._result(
                    final_text_parts,
                    response.stop_reason or "end_turn",
                    i + 1,
                    tool_calls,
                    total_in,
                    total_out,
                )

            tool_results: list[dict[str, Any]] = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                tool_input = dict(block.input) if block.input else {}

                if block.name == "wait":
                    self._emit({"type": "wait", "iteration": i})
                    return self._result(
                        final_text_parts,
                        "wait",
                        i + 1,
                        tool_calls,
                        total_in,
                        total_out,
                    )

                self._emit({"type": "tool_use", "iteration": i, "name": block.name, "input": tool_input})
                output = tool_register.call_tool(block.name, tool_input)
                self._emit({"type": "tool_result", "iteration": i, "output": output})
                tool_calls.append(ToolCall(block.name, tool_input, output))

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output,
                    }
                )

            messages.append({"role": "user", "content": tool_results})

        return self._result(
            final_text_parts,
            "max_iterations",
            self.max_iterations,
            tool_calls,
            total_in,
            total_out,
        )

    def run_cycle(self, user_input: str) -> CycleResult:
        started = datetime.utcnow()

        ## init with system prompt
        initial = self._build_initial_user_message(user_input)
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": initial},
        ]

        # init tools
        tool_calls: list[ToolCall] = []

        final_text_parts: list[str] = []
        ## token usage
        total_in = 0
        total_out = 0
        ## loop counts
        iterations_attempted = 0
        result: CycleResult | None = None
        error_text: str | None = None

        try:
            for i in range(self.max_iterations):
                iterations_attempted = i + 1
                # Micro-compact old tool_results before sending, so context
                # doesn't balloon across many tool roundtrips.
                _micro_compact_tool_results(messages, keep_recent=1)

                # send message to model
                response = self.client.messages.create(
                    model=self.model,
                    system=self.system_prompt,
                    tools=tool_register.TOOL_SPECS,
                    messages=messages,
                    max_tokens=self.max_tokens_per_call,
                )

                # count token usage
                total_in += response.usage.input_tokens
                total_out += response.usage.output_tokens

                # llm response text content.
                iter_text_parts: list[str] = []

                for block in response.content:
                    if block.type == "text":
                        iter_text_parts.append(block.text)
                        self._emit({"type": "assistant_text", "iteration": i, "text": block.text})
                if iter_text_parts:
                    final_text_parts = iter_text_parts

                messages.append({"role": "assistant", "content": response.content})

                if response.stop_reason != "tool_use": # end turn, just return the text content and stop reason.
                    result = self._result(
                        final_text_parts,
                        response.stop_reason or "end_turn",
                        i + 1,
                        tool_calls,
                        total_in,
                        total_out,
                    )
                    return result

                # tool use situations, call the tool and append the result to messages for next iteration.
                tool_results: list[dict[str, Any]] = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue
                    tool_input = dict(block.input) if block.input else {}

                    if block.name == "wait":
                        self._emit({"type": "wait", "iteration": i})
                        result = self._result(
                            final_text_parts,
                            "wait",
                            i + 1,
                            tool_calls,
                            total_in,
                            total_out,
                        )
                        return result

                    self._emit({"type": "tool_use", "iteration": i, "name": block.name, "input": tool_input})
                    output = tool_register.call_tool(block.name, tool_input)

                    self._emit({"type": "tool_result", "iteration": i, "output": output})
                    tool_calls.append(ToolCall(block.name, tool_input, output))

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": output,
                        }
                    )

                messages.append({"role": "user", "content": tool_results})

            result = self._result(
                final_text_parts,
                "max_iterations",
                self.max_iterations,
                tool_calls,
                total_in,
                total_out,
            )
            return result

        except BaseException:
            # Capture the full traceback for the audit row, then re-raise so
            # the caller still sees the failure. BaseException covers
            # KeyboardInterrupt / SystemExit too; we don't suppress, only log.
            error_text = traceback.format_exc()
            raise

        finally:
            ended = datetime.utcnow()
            if result is None:
                result = self._result(
                    final_text_parts,
                    "error",
                    iterations_attempted,
                    tool_calls,
                    total_in,
                    total_out,
                )
            try:
                audit.log_cycle(
                    self._db,
                    result=result,
                    messages=messages,
                    user_input=user_input,
                    started=started,
                    ended=ended,
                    error_text=error_text,
                )
            except Exception as audit_exc:
                # Logging must never mask the real outcome of the cycle.
                print(f"[warn] audit log failed: {audit_exc}")

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
