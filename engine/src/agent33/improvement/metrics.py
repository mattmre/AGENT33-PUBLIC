"""Improvement metrics computation (IM-01..IM-05).

Implements the improvement metrics from
``core/orchestrator/CONTINUOUS_IMPROVEMENT.md``.
"""

from __future__ import annotations

import logging

from agent33.improvement.models import (
    ImprovementMetric,
    MetricsSnapshot,
    MetricTrend,
)

logger = logging.getLogger(__name__)


def percentile(values: list[float], p: float) -> float:
    """Compute the p-th percentile of a sorted list of values.

    ``p`` is in the range [0, 1].  Returns 0.0 for empty inputs.
    """
    if not values:
        return 0.0
    sorted_values = sorted(values)
    if p <= 0:
        return sorted_values[0]
    if p >= 1:
        return sorted_values[-1]
    index = int(round((len(sorted_values) - 1) * p))
    return sorted_values[index]


# ---------------------------------------------------------------------------
# Canonical metric definitions
# ---------------------------------------------------------------------------

_METRIC_DEFS: list[tuple[str, str, str, float]] = [
    # (metric_id, name, unit, default_target)
    ("IM-01", "Cycle time", "hours", 0.0),  # decreasing trend
    ("IM-02", "Rework rate", "percent", 15.0),  # < 15%
    ("IM-03", "First-pass success", "percent", 85.0),  # > 85%
    ("IM-04", "Documentation lag", "sprints", 1.0),  # < 1 sprint
    ("IM-05", "Research intake velocity", "items/quarter", 5.0),  # 5+ items
]


def default_metrics() -> list[ImprovementMetric]:
    """Return the five canonical metrics with default values."""
    return [
        ImprovementMetric(
            metric_id=mid,
            name=name,
            unit=unit,
            target=target,
        )
        for mid, name, unit, target in _METRIC_DEFS
    ]


def compute_trend(values: list[float], *, threshold: float = 0.05) -> MetricTrend:
    """Compute trend direction from a list of chronological values.

    Uses simple linear comparison of first-half average vs second-half
    average.  If fewer than 2 values, returns STABLE.

    *threshold* is the fractional change required to declare a trend
    (default 5%).
    """
    if len(values) < 2:
        return MetricTrend.STABLE

    mid = len(values) // 2
    first_half = sum(values[:mid]) / max(mid, 1)
    second_half = sum(values[mid:]) / max(len(values) - mid, 1)

    if second_half > first_half * (1.0 + threshold):
        return MetricTrend.IMPROVING
    if second_half < first_half * (1.0 - threshold):
        return MetricTrend.DECLINING
    return MetricTrend.STABLE


class MetricsTracker:
    """Track and query improvement metrics snapshots."""

    def __init__(self) -> None:
        self._snapshots: list[MetricsSnapshot] = []

    def save_snapshot(self, snapshot: MetricsSnapshot) -> MetricsSnapshot:
        """Store a metrics snapshot."""
        self._snapshots.append(snapshot)
        return snapshot

    def latest(self) -> MetricsSnapshot | None:
        """Return the most recent snapshot, or None."""
        if not self._snapshots:
            return None
        return self._snapshots[-1]

    def list_snapshots(self, limit: int = 10) -> list[MetricsSnapshot]:
        """Return the most recent N snapshots (newest first)."""
        return list(reversed(self._snapshots[-limit:]))

    def get_trend(self, metric_id: str, periods: int = 4) -> tuple[MetricTrend, list[float]]:
        """Compute trend for a specific metric across recent snapshots.

        Returns (trend_direction, chronological values).
        """
        values: list[float] = []
        for snap in self._snapshots[-periods:]:
            for m in snap.metrics:
                if m.metric_id == metric_id:
                    values.append(m.current)
                    break
        return compute_trend(values), values
