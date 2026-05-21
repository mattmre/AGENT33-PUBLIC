"""ToolLoopScorer -- thread-safe accumulator for tool-loop runtime metrics."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class IterationRecord:
    """A single recorded tool-loop iteration."""

    agent_id: str
    tool_calls: int
    success: bool
    converged: bool
    recorded_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


class ToolLoopScorer:
    """Thread-safe accumulator for tool-loop metrics from agent invocations.

    Records are accumulated in memory.  The scorer is intended to live on
    ``app.state.tool_loop_scorer`` and be injected into
    :class:`~agent33.agents.runtime.AgentRuntime` so that completed
    ``invoke_iterative`` calls record their results here.

    ``get_loop_summary()`` returns a plain ``dict`` suitable for direct JSON
    serialisation by the ``GET /v1/agents/tool-loop/scores`` route.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._iterations: list[IterationRecord] = []
        self._tool_call_counts: dict[str, int] = {}

    def record_iteration(
        self, agent_id: str, tool_calls: int, success: bool
    ) -> None:
        """Record one completed tool-loop iteration.

        Parameters
        ----------
        agent_id:
            Name or ID of the agent that completed the iteration.
        tool_calls:
            Number of tool calls executed during this iteration.
        success:
            ``True`` if the iteration completed without an error.
        """
        converged = tool_calls == 0 and success
        with self._lock:
            self._iterations.append(
                IterationRecord(
                    agent_id=agent_id,
                    tool_calls=tool_calls,
                    success=success,
                    converged=converged,
                )
            )
            self._tool_call_counts[agent_id] = (
                self._tool_call_counts.get(agent_id, 0) + tool_calls
            )

    def get_loop_summary(self) -> dict[str, Any]:
        """Return an aggregated summary of all recorded iterations.

        Returns
        -------
        dict
            Keys: ``total_iterations``, ``total_tool_calls``, ``unique_agents``,
            ``overall_success_rate``, ``convergence_rate``, and ``iterations``
            (last 100 records as dicts).
        """
        with self._lock:
            total = len(self._iterations)
            if total == 0:
                return {
                    "total_iterations": 0,
                    "total_tool_calls": 0,
                    "unique_agents": 0,
                    "overall_success_rate": 0.0,
                    "convergence_rate": 0.0,
                    "iterations": [],
                }
            successes = sum(1 for r in self._iterations if r.success)
            converged = sum(1 for r in self._iterations if r.converged)
            return {
                "total_iterations": total,
                "total_tool_calls": sum(r.tool_calls for r in self._iterations),
                "unique_agents": len(self._tool_call_counts),
                "overall_success_rate": round(successes / total, 4),
                "convergence_rate": round(converged / total, 4),
                "iterations": [
                    {
                        "agent_id": r.agent_id,
                        "tool_calls": r.tool_calls,
                        "success": r.success,
                        "converged": r.converged,
                        "recorded_at": r.recorded_at,
                    }
                    for r in self._iterations[-100:]
                ],
            }
