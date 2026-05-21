"""Agent performance profiling and bottleneck detection.

Provides per-agent invocation profiling with phase-level timing breakdown
(prompt construction, LLM call, tool execution, post-processing), summary
statistics (p95, averages, success rates), bottleneck detection, and hot-path
identification.

Profiles are stored in a bounded ring buffer to avoid unbounded memory growth.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict, deque
from datetime import datetime  # noqa: TCH003
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AgentInvocationProfile(BaseModel):
    """Timing and resource profile for a single agent invocation."""

    agent_name: str
    invocation_id: str
    started_at: datetime
    completed_at: datetime | None = None
    total_duration_ms: float
    prompt_construction_ms: float
    llm_call_ms: float
    tool_calls_ms: float
    post_processing_ms: float
    token_input: int
    token_output: int
    tool_call_count: int
    model_id: str
    success: bool


class AgentPerformanceSummary(BaseModel):
    """Aggregated performance statistics for an agent."""

    agent_name: str
    total_invocations: int
    avg_duration_ms: float
    p95_duration_ms: float
    avg_llm_ms: float
    avg_tool_ms: float
    success_rate: float
    avg_token_input: float
    avg_token_output: float
    bottleneck: str = Field(
        description="Which phase is slowest on average: 'llm', 'tools', 'prompt', or 'post'"
    )


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Compute the given percentile from a pre-sorted list of values.

    Uses linear interpolation between adjacent ranks.
    """
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    # Rank (0-indexed fractional position)
    rank = (pct / 100.0) * (n - 1)
    lo = int(rank)
    hi = min(lo + 1, n - 1)
    frac = rank - lo
    return sorted_values[lo] + frac * (sorted_values[hi] - sorted_values[lo])


class AgentProfiler:
    """Collects and analyses per-agent invocation profiles.

    Uses a bounded ring buffer to limit memory usage.  Thread-safe for
    concurrent recording from async handlers.

    Parameters
    ----------
    max_profiles:
        Maximum number of profiles to retain.  When the limit is reached,
        the oldest profile is evicted.
    """

    def __init__(self, max_profiles: int = 1000) -> None:
        self._profiles: deque[AgentInvocationProfile] = deque(maxlen=max(1, max_profiles))
        self._lock = threading.Lock()

    # -- recording ----------------------------------------------------------

    def record_profile(self, profile: AgentInvocationProfile) -> None:
        """Store a profile, evicting the oldest if the buffer is full."""
        with self._lock:
            self._profiles.append(profile)

    # -- retrieval ----------------------------------------------------------

    def get_profiles(
        self,
        agent_name: str | None = None,
        limit: int = 50,
    ) -> list[AgentInvocationProfile]:
        """Return recent profiles, optionally filtered by agent name.

        Results are ordered newest-first.
        """
        with self._lock:
            if agent_name is not None:
                matched = [p for p in self._profiles if p.agent_name == agent_name]
            else:
                matched = list(self._profiles)
        # Newest first, then apply limit
        return list(reversed(matched))[:limit]

    # -- summaries ----------------------------------------------------------

    def get_agent_summary(self, agent_name: str) -> AgentPerformanceSummary:
        """Compute a performance summary for a single agent.

        Raises
        ------
        KeyError
            If no profiles exist for the given agent.
        """
        with self._lock:
            agent_profiles = [p for p in self._profiles if p.agent_name == agent_name]

        if not agent_profiles:
            raise KeyError(f"No profiles for agent '{agent_name}'")

        return self._build_summary(agent_name, agent_profiles)

    def get_all_summaries(self) -> list[AgentPerformanceSummary]:
        """Return summaries for all agents that have at least one profile."""
        with self._lock:
            by_agent: dict[str, list[AgentInvocationProfile]] = defaultdict(list)
            for p in self._profiles:
                by_agent[p.agent_name].append(p)

        summaries = [
            self._build_summary(name, profiles) for name, profiles in sorted(by_agent.items())
        ]
        return summaries

    # -- bottleneck detection -----------------------------------------------

    def detect_bottlenecks(self) -> list[dict[str, Any]]:
        """Identify agents where one phase dominates > 60% of average duration.

        Returns a list of dicts with keys: ``agent_name``, ``bottleneck_phase``,
        ``phase_avg_ms``, ``total_avg_ms``, ``ratio``.

        Takes a single snapshot under one lock acquisition to avoid inconsistent
        ratios when profiles are recorded concurrently.
        """
        # Single snapshot — all computation derives from this copy
        with self._lock:
            profiles_copy = list(self._profiles)

        if not profiles_copy:
            return []

        # Group by agent
        by_agent: dict[str, list[AgentInvocationProfile]] = defaultdict(list)
        for p in profiles_copy:
            by_agent[p.agent_name].append(p)

        results: list[dict[str, Any]] = []
        for agent_name, agent_profiles in sorted(by_agent.items()):
            summary = self._build_summary(agent_name, agent_profiles)
            if summary.avg_duration_ms <= 0:
                continue

            # Compute all phase averages from the same snapshot
            n = len(agent_profiles)
            avg_prompt = sum(p.prompt_construction_ms for p in agent_profiles) / n
            avg_post = sum(p.post_processing_ms for p in agent_profiles) / n

            phases = {
                "llm": summary.avg_llm_ms,
                "tools": summary.avg_tool_ms,
                "prompt": avg_prompt,
                "post": avg_post,
            }

            for phase_name, phase_avg in phases.items():
                ratio = phase_avg / summary.avg_duration_ms
                if ratio > 0.6:
                    results.append(
                        {
                            "agent_name": agent_name,
                            "bottleneck_phase": phase_name,
                            "phase_avg_ms": round(phase_avg, 2),
                            "total_avg_ms": round(summary.avg_duration_ms, 2),
                            "ratio": round(ratio, 4),
                        }
                    )
        return results

    # -- hot paths ----------------------------------------------------------

    def get_hot_paths(self) -> list[dict[str, Any]]:
        """Identify the slowest agent/model combinations.

        Returns a list of dicts sorted by average duration (descending) with
        keys: ``agent_name``, ``model_id``, ``invocations``, ``avg_duration_ms``,
        ``max_duration_ms``.
        """
        with self._lock:
            profiles_copy = list(self._profiles)

        # Group by (agent_name, model_id)
        grouped: dict[tuple[str, str], list[AgentInvocationProfile]] = defaultdict(list)
        for p in profiles_copy:
            grouped[(p.agent_name, p.model_id)].append(p)

        results: list[dict[str, Any]] = []
        for (agent_name, model_id), profiles in grouped.items():
            durations = [p.total_duration_ms for p in profiles]
            avg = sum(durations) / len(durations)
            results.append(
                {
                    "agent_name": agent_name,
                    "model_id": model_id,
                    "invocations": len(profiles),
                    "avg_duration_ms": round(avg, 2),
                    "max_duration_ms": round(max(durations), 2),
                }
            )

        results.sort(key=lambda r: r["avg_duration_ms"], reverse=True)
        return results

    # -- internal -----------------------------------------------------------

    @staticmethod
    def _build_summary(
        agent_name: str,
        profiles: list[AgentInvocationProfile],
    ) -> AgentPerformanceSummary:
        """Build a performance summary from a list of profiles."""
        n = len(profiles)
        durations = sorted(p.total_duration_ms for p in profiles)
        llm_times = [p.llm_call_ms for p in profiles]
        tool_times = [p.tool_calls_ms for p in profiles]
        prompt_times = [p.prompt_construction_ms for p in profiles]
        post_times = [p.post_processing_ms for p in profiles]
        token_in = [p.token_input for p in profiles]
        token_out = [p.token_output for p in profiles]
        successes = sum(1 for p in profiles if p.success)

        avg_llm = sum(llm_times) / n
        avg_tool = sum(tool_times) / n
        avg_prompt = sum(prompt_times) / n
        avg_post = sum(post_times) / n

        # Determine bottleneck: which phase has the highest average
        phase_avgs = {
            "llm": avg_llm,
            "tools": avg_tool,
            "prompt": avg_prompt,
            "post": avg_post,
        }
        bottleneck = max(phase_avgs, key=lambda k: phase_avgs[k])

        return AgentPerformanceSummary(
            agent_name=agent_name,
            total_invocations=n,
            avg_duration_ms=round(sum(durations) / n, 2),
            p95_duration_ms=round(_percentile(durations, 95), 2),
            avg_llm_ms=round(avg_llm, 2),
            avg_tool_ms=round(avg_tool, 2),
            success_rate=round(successes / n, 4) if n > 0 else 0.0,
            avg_token_input=round(sum(token_in) / n, 2),
            avg_token_output=round(sum(token_out) / n, 2),
            bottleneck=bottleneck,
        )
