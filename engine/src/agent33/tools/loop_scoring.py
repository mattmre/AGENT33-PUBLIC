"""Scoring and retry patterns for iterative tool-use loops.

Provides models and a scorer class that track individual tool call
outcomes within an iterative agent loop, compute per-tool effectiveness
scores, detect convergence across iterations, and decide whether a
failed call should be retried (with exponential backoff).

The composite effectiveness score combines three signals:
    success_rate * 0.4  +  (1 - retry_rate) * 0.3  +  speed_score * 0.3

where ``speed_score`` normalises average duration against a 10-second
baseline so that faster tools score higher.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections import defaultdict
from datetime import UTC, datetime

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Duration baseline used to normalise the speed component of the score.
_SPEED_BASELINE_MS: float = 10_000.0


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ToolCallRecord(BaseModel):
    """A single recorded tool call within a loop iteration."""

    tool_name: str
    call_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    success: bool
    duration_ms: float
    retry_count: int = 0
    error: str | None = None
    input_hash: str = ""


class ToolEffectivenessScore(BaseModel):
    """Composite effectiveness score for a single tool."""

    tool_name: str
    total_calls: int
    successful_calls: int
    failed_calls: int
    success_rate: float
    avg_duration_ms: float
    retry_rate: float  # fraction of calls that had retry_count > 0
    score: float  # 0..1 weighted composite


class LoopIteration(BaseModel):
    """Snapshot of one iteration within the tool loop."""

    iteration: int
    tool_calls: list[ToolCallRecord]
    cumulative_success_rate: float
    converging: bool


class ToolLoopSummary(BaseModel):
    """Aggregate analytics for an entire tool loop execution."""

    total_iterations: int
    total_tool_calls: int
    unique_tools: int
    overall_success_rate: float
    convergence_detected: bool
    tool_scores: list[ToolEffectivenessScore]
    iterations: list[LoopIteration]


class RetryPolicy(BaseModel):
    """Policy governing automated retries of failed tool calls."""

    max_retries: int = 3
    backoff_base_ms: float = 100
    backoff_multiplier: float = 2.0
    backoff_max_ms: float = 5000
    retry_on_errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------


def _compute_input_hash(data: str) -> str:
    """Return a short SHA-256 hex digest for dedup detection."""
    return hashlib.sha256(data.encode()).hexdigest()[:16]


class ToolLoopScorer:
    """Tracks tool call records and computes loop-level analytics.

    Parameters
    ----------
    retry_policy:
        Optional retry policy.  When ``None``, a default ``RetryPolicy``
        is used.
    """

    def __init__(self, retry_policy: RetryPolicy | None = None) -> None:
        self._policy = retry_policy or RetryPolicy()
        self._records: list[ToolCallRecord] = []
        # Each iteration is a list of records accumulated after the most
        # recent ``start_iteration()`` call.
        self._iterations: list[list[ToolCallRecord]] = []
        self._current_iteration: list[ToolCallRecord] = []

    # -- Recording ----------------------------------------------------------

    def record_call(
        self,
        tool_name: str,
        success: bool,
        duration_ms: float,
        error: str | None = None,
        retry_count: int = 0,
        input_hash: str = "",
    ) -> ToolCallRecord:
        """Record a single tool call and return the created record."""
        record = ToolCallRecord(
            tool_name=tool_name,
            success=success,
            duration_ms=duration_ms,
            error=error,
            retry_count=retry_count,
            input_hash=input_hash,
        )
        self._records.append(record)
        self._current_iteration.append(record)
        return record

    # -- Per-tool scoring ---------------------------------------------------

    def get_tool_score(self, tool_name: str) -> ToolEffectivenessScore:
        """Compute the effectiveness score for a single tool.

        Raises ``KeyError`` if no calls have been recorded for
        *tool_name*.
        """
        calls = [r for r in self._records if r.tool_name == tool_name]
        if not calls:
            raise KeyError(f"No records for tool '{tool_name}'")
        return self._score_for(tool_name, calls)

    def get_all_scores(self) -> list[ToolEffectivenessScore]:
        """Return effectiveness scores for every tool that has records."""
        grouped: dict[str, list[ToolCallRecord]] = defaultdict(list)
        for r in self._records:
            grouped[r.tool_name].append(r)
        return [self._score_for(name, calls) for name, calls in sorted(grouped.items())]

    # -- Loop summary -------------------------------------------------------

    def get_loop_summary(self) -> ToolLoopSummary:
        """Return full analytics for the recorded tool loop."""
        # Finalise the current iteration if it has calls.
        iterations_snapshot = list(self._iterations)
        if self._current_iteration:
            iterations_snapshot.append(list(self._current_iteration))

        total_calls = len(self._records)
        successful = sum(1 for r in self._records if r.success)
        unique_tools = len({r.tool_name for r in self._records})
        overall_success_rate = successful / total_calls if total_calls else 0.0

        loop_iterations: list[LoopIteration] = []
        cumulative_calls = 0
        cumulative_success = 0
        prev_rate: float | None = None

        for idx, it_records in enumerate(iterations_snapshot):
            cumulative_calls += len(it_records)
            cumulative_success += sum(1 for r in it_records if r.success)
            rate = cumulative_success / cumulative_calls if cumulative_calls else 0.0
            converging = rate > prev_rate if prev_rate is not None else False
            loop_iterations.append(
                LoopIteration(
                    iteration=idx + 1,
                    tool_calls=list(it_records),
                    cumulative_success_rate=round(rate, 4),
                    converging=converging,
                )
            )
            prev_rate = rate

        convergence = self.detect_convergence()
        tool_scores = self.get_all_scores()

        return ToolLoopSummary(
            total_iterations=len(iterations_snapshot),
            total_tool_calls=total_calls,
            unique_tools=unique_tools,
            overall_success_rate=round(overall_success_rate, 4),
            convergence_detected=convergence,
            tool_scores=tool_scores,
            iterations=loop_iterations,
        )

    # -- Retry logic --------------------------------------------------------

    def should_retry(
        self,
        tool_name: str,
        attempt: int,
        error: str,
    ) -> tuple[bool, float]:
        """Decide whether to retry a failed tool call.

        Returns ``(should_retry, wait_ms)``.  ``wait_ms`` is the
        recommended wait before retrying (exponential backoff capped
        at ``backoff_max_ms``).
        """
        policy = self._policy
        if attempt >= policy.max_retries:
            return False, 0.0

        # If policy restricts to specific errors, check the list.
        if policy.retry_on_errors:
            matched = any(pattern.lower() in error.lower() for pattern in policy.retry_on_errors)
            if not matched:
                return False, 0.0

        wait = min(
            policy.backoff_base_ms * (policy.backoff_multiplier**attempt),
            policy.backoff_max_ms,
        )
        return True, wait

    # -- Iteration tracking -------------------------------------------------

    def start_iteration(self) -> None:
        """Mark the start of a new loop iteration."""
        if self._current_iteration:
            self._iterations.append(list(self._current_iteration))
        self._current_iteration = []

    def detect_convergence(self) -> bool:
        """Return ``True`` if success rate is improving across recent iterations.

        Convergence is detected when at least the last two completed
        iterations show a non-decreasing cumulative success rate and the
        most recent rate exceeds the one before it.
        """
        snapshot = list(self._iterations)
        if self._current_iteration:
            snapshot.append(list(self._current_iteration))

        if len(snapshot) < 2:
            return False

        # Compute per-iteration success rates.
        rates: list[float] = []
        for it_records in snapshot:
            if not it_records:
                rates.append(0.0)
                continue
            rates.append(sum(1 for r in it_records if r.success) / len(it_records))

        # Convergence: last rate > previous rate.
        return rates[-1] > rates[-2]

    # -- Reset --------------------------------------------------------------

    def reset(self) -> None:
        """Clear all recorded data."""
        self._records.clear()
        self._iterations.clear()
        self._current_iteration.clear()

    # -- Internal helpers ---------------------------------------------------

    @staticmethod
    def _score_for(
        tool_name: str,
        calls: list[ToolCallRecord],
    ) -> ToolEffectivenessScore:
        total = len(calls)
        successful = sum(1 for c in calls if c.success)
        failed = total - successful
        success_rate = successful / total if total else 0.0

        avg_duration = sum(c.duration_ms for c in calls) / total if total else 0.0
        retried = sum(1 for c in calls if c.retry_count > 0)
        retry_rate = retried / total if total else 0.0

        # speed_score: 1.0 when instant, approaching 0 when at or above baseline.
        speed_score = max(0.0, 1.0 - avg_duration / _SPEED_BASELINE_MS)

        composite = success_rate * 0.4 + (1.0 - retry_rate) * 0.3 + speed_score * 0.3

        return ToolEffectivenessScore(
            tool_name=tool_name,
            total_calls=total,
            successful_calls=successful,
            failed_calls=failed,
            success_rate=round(success_rate, 4),
            avg_duration_ms=round(avg_duration, 2),
            retry_rate=round(retry_rate, 4),
            score=round(composite, 4),
        )
