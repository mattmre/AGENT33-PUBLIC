"""Streaming events emitted during tool-loop execution."""

from __future__ import annotations

import dataclasses
import time
from typing import Any, Literal

EventType = Literal[
    "loop_started",
    "iteration_started",
    "llm_request",
    "llm_token",
    "llm_response",
    "tool_call_requested",
    "tool_call_started",
    "tool_call_completed",
    "tool_call_blocked",
    "loop_detected",
    "handoff_context_wipe",
    "confirmation_prompt",
    "confirmation_result",
    "context_managed",
    "context_compressed",
    "delegation_started",
    "delegation_progress",
    "delegation_completed",
    "error",
    "completed",
]


@dataclasses.dataclass(frozen=True, slots=True)
class ToolLoopEvent:
    """A single streaming event from the agent tool loop."""

    event_type: EventType
    iteration: int
    timestamp: float = dataclasses.field(default_factory=time.time)
    data: dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_sse(self) -> str:
        """Serialize as an SSE data line."""
        import json

        payload = {
            "event_type": self.event_type,
            "iteration": self.iteration,
            "timestamp": self.timestamp,
            "data": self.data,
        }
        return f"data: {json.dumps(payload)}\n\n"
