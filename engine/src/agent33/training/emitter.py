"""Structured trace emission for agent execution rollouts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class Span:
    """A single span in an execution trace."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    rollout_id: str = ""
    span_type: str = ""  # prompt, tool_call, result, reward
    agent_name: str = ""
    content: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    parent_span_id: str = ""


class TraceEmitter:
    """Emits structured spans for a single rollout execution.

    A rollout represents one complete agent invocation cycle.
    Spans capture prompts, tool calls, results, and reward signals.
    """

    def __init__(self) -> None:
        self._rollout_id: str = ""
        self._spans: list[Span] = []

    @property
    def rollout_id(self) -> str:
        return self._rollout_id

    def new_rollout(self) -> str:
        """Start a new rollout, clearing previous spans."""
        self._rollout_id = uuid.uuid4().hex
        self._spans = []
        return self._rollout_id

    def emit_prompt(self, agent: str, messages: list[dict[str, str]]) -> str:
        """Record a prompt span."""
        import json

        span = Span(
            rollout_id=self._rollout_id,
            span_type="prompt",
            agent_name=agent,
            content=json.dumps(messages),
        )
        self._spans.append(span)
        return span.id

    def emit_tool_call(self, agent: str, tool: str, params: dict[str, object]) -> str:
        """Record a tool call span."""
        import json

        span = Span(
            rollout_id=self._rollout_id,
            span_type="tool_call",
            agent_name=agent,
            content=json.dumps({"tool": tool, "params": params}, default=str),
        )
        self._spans.append(span)
        return span.id

    def emit_result(self, agent: str, output: str, parent_id: str = "") -> str:
        """Record a result span."""
        span = Span(
            rollout_id=self._rollout_id,
            span_type="result",
            agent_name=agent,
            content=output,
            parent_span_id=parent_id,
        )
        self._spans.append(span)
        return span.id

    def emit_reward(self, agent: str, score: float, reason: str = "") -> str:
        """Record a reward signal span."""
        import json

        span = Span(
            rollout_id=self._rollout_id,
            span_type="reward",
            agent_name=agent,
            content=json.dumps({"score": score, "reason": reason}),
        )
        self._spans.append(span)
        return span.id

    def collect(self) -> list[Span]:
        """Return all spans for the current rollout."""
        return list(self._spans)
