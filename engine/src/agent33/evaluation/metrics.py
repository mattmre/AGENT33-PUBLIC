"""Metrics calculator for evaluation runs.

Computes M-01 through M-05 from ``core/arch/evaluation-harness.md``.
"""

from __future__ import annotations

from agent33.evaluation.models import MetricId, MetricValue, TaskResult, TaskRunResult


class MetricsCalculator:
    """Calculate evaluation metrics from golden task results."""

    def compute_all(
        self,
        results: list[TaskRunResult],
        rework_count: int = 0,
        scope_violations: int = 0,
    ) -> list[MetricValue]:
        """Compute all metrics from task results.

        Parameters
        ----------
        results:
            List of golden task / case run results.
        rework_count:
            Number of tasks that required rework (for M-03).
        scope_violations:
            Number of tasks with scope violations (for M-05).
        """
        return [
            self.success_rate(results),
            self.time_to_green(results),
            self.rework_rate(results, rework_count),
            self.diff_size(results),
            self.scope_adherence(results, scope_violations),
        ]

    def success_rate(self, results: list[TaskRunResult]) -> MetricValue:
        """M-01: Percentage of tasks passing on first attempt."""
        if not results:
            return MetricValue(metric_id=MetricId.M_01, value=0.0, unit="%")
        passed = sum(1 for r in results if r.result == TaskResult.PASS)
        value = (passed / len(results)) * 100
        return MetricValue(metric_id=MetricId.M_01, value=round(value, 2), unit="%")

    def time_to_green(self, results: list[TaskRunResult]) -> MetricValue:
        """M-02: Average time-to-green in milliseconds."""
        durations = [r.duration_ms for r in results if r.duration_ms > 0]
        if not durations:
            return MetricValue(metric_id=MetricId.M_02, value=0.0, unit="ms")
        avg = sum(durations) / len(durations)
        return MetricValue(metric_id=MetricId.M_02, value=round(avg, 2), unit="ms")

    def rework_rate(self, results: list[TaskRunResult], rework_count: int = 0) -> MetricValue:
        """M-03: Percentage of tasks requiring rework."""
        if not results:
            return MetricValue(metric_id=MetricId.M_03, value=0.0, unit="%")
        value = (rework_count / len(results)) * 100
        return MetricValue(metric_id=MetricId.M_03, value=round(value, 2), unit="%")

    def diff_size(self, results: list[TaskRunResult]) -> MetricValue:
        """M-04: Average diff size (uses checks_total as proxy for lines changed)."""
        totals = [r.checks_total for r in results if r.checks_total > 0]
        if not totals:
            return MetricValue(metric_id=MetricId.M_04, value=0.0, unit="lines")
        avg = sum(totals) / len(totals)
        return MetricValue(metric_id=MetricId.M_04, value=round(avg, 2), unit="lines")

    def scope_adherence(
        self, results: list[TaskRunResult], scope_violations: int = 0
    ) -> MetricValue:
        """M-05: Percentage of tasks completed within scope."""
        if not results:
            return MetricValue(metric_id=MetricId.M_05, value=0.0, unit="%")
        within_scope = len(results) - scope_violations
        value = (within_scope / len(results)) * 100
        return MetricValue(metric_id=MetricId.M_05, value=round(value, 2), unit="%")
