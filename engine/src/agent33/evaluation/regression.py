"""Regression detection and recording.

Implements the regression indicators (RI-01..RI-05) and regression record
schema from ``core/arch/REGRESSION_GATES.md``.
"""

from __future__ import annotations

import logging

from agent33.evaluation.models import (
    BaselineSnapshot,
    MetricId,
    MetricValue,
    RegressionIndicator,
    RegressionRecord,
    RegressionSeverity,
    TaskResult,
    TaskRunResult,
    TriageStatus,
)

logger = logging.getLogger(__name__)

# Indicator → default severity mapping (§ Regression Indicators)
_INDICATOR_SEVERITY: dict[RegressionIndicator, RegressionSeverity] = {
    RegressionIndicator.RI_01: RegressionSeverity.HIGH,
    RegressionIndicator.RI_02: RegressionSeverity.MEDIUM,
    RegressionIndicator.RI_03: RegressionSeverity.MEDIUM,
    RegressionIndicator.RI_04: RegressionSeverity.LOW,
    RegressionIndicator.RI_05: RegressionSeverity.HIGH,
}

# Significant increase threshold for time-to-green (RI-04)
TTG_INCREASE_FACTOR = 1.5  # 50% increase = significant


class RegressionDetector:
    """Detect regressions by comparing current results to a baseline."""

    def detect(
        self,
        baseline: BaselineSnapshot,
        current_metrics: list[MetricValue],
        current_results: list[TaskRunResult],
        thresholds: dict[MetricId, float] | None = None,
    ) -> list[RegressionRecord]:
        """Compare current evaluation to baseline and detect regressions.

        Parameters
        ----------
        baseline:
            Previous baseline snapshot to compare against.
        current_metrics:
            Current evaluation metric values.
        current_results:
            Current golden task/case results.
        thresholds:
            Optional metric thresholds (for RI-02 detection).
        """
        regressions: list[RegressionRecord] = []

        # RI-01: Previously passing task now fails
        regressions.extend(self._detect_task_regressions(baseline.task_results, current_results))

        # RI-02: Metric drops below threshold
        if thresholds:
            regressions.extend(
                self._detect_threshold_breaches(baseline.metrics, current_metrics, thresholds)
            )

        # RI-04: Time-to-green increases significantly
        regressions.extend(self._detect_ttg_increase(baseline.metrics, current_metrics))

        for reg in regressions:
            logger.info(
                "regression_detected id=%s indicator=%s severity=%s",
                reg.regression_id,
                reg.indicator.value,
                reg.severity.value,
            )

        return regressions

    def _detect_task_regressions(
        self,
        baseline_results: list[TaskRunResult],
        current_results: list[TaskRunResult],
    ) -> list[RegressionRecord]:
        """RI-01: Detect tasks that previously passed but now fail."""
        baseline_map = {r.item_id: r for r in baseline_results}
        regressions: list[RegressionRecord] = []

        for current in current_results:
            prev = baseline_map.get(current.item_id)
            if prev is None:
                continue
            if prev.result == TaskResult.PASS and current.result == TaskResult.FAIL:
                regressions.append(
                    RegressionRecord(
                        indicator=RegressionIndicator.RI_01,
                        description=(
                            f"Task {current.item_id} previously passed "
                            f"but now fails: {current.notes}"
                        ),
                        severity=_INDICATOR_SEVERITY[RegressionIndicator.RI_01],
                        affected_tasks=[current.item_id],
                    )
                )
        return regressions

    def _detect_threshold_breaches(
        self,
        baseline_metrics: list[MetricValue],
        current_metrics: list[MetricValue],
        thresholds: dict[MetricId, float],
    ) -> list[RegressionRecord]:
        """RI-02: Detect metrics that drop below their threshold."""
        baseline_map = {m.metric_id: m.value for m in baseline_metrics}
        current_map = {m.metric_id: m.value for m in current_metrics}
        regressions: list[RegressionRecord] = []

        for metric_id, threshold_val in thresholds.items():
            current_val = current_map.get(metric_id, 0.0)
            prev_val = baseline_map.get(metric_id, 0.0)

            # For metrics where higher is better (M-01, M-05): breach when below
            # For metrics where lower is better (M-03): breach when above
            breached = False
            if metric_id in (MetricId.M_01, MetricId.M_05):
                breached = current_val < threshold_val and prev_val >= threshold_val
            elif metric_id == MetricId.M_03:
                breached = current_val > threshold_val and prev_val <= threshold_val

            if breached:
                regressions.append(
                    RegressionRecord(
                        indicator=RegressionIndicator.RI_02,
                        description=(
                            f"Metric {metric_id.value} dropped below threshold: "
                            f"{current_val} (threshold: {threshold_val}, was: {prev_val})"
                        ),
                        metric_id=metric_id,
                        previous_value=prev_val,
                        current_value=current_val,
                        threshold_value=threshold_val,
                        severity=_INDICATOR_SEVERITY[RegressionIndicator.RI_02],
                    )
                )
        return regressions

    def _detect_ttg_increase(
        self,
        baseline_metrics: list[MetricValue],
        current_metrics: list[MetricValue],
    ) -> list[RegressionRecord]:
        """RI-04: Detect significant time-to-green increase."""
        baseline_ttg = next(
            (m.value for m in baseline_metrics if m.metric_id == MetricId.M_02), 0.0
        )
        current_ttg = next((m.value for m in current_metrics if m.metric_id == MetricId.M_02), 0.0)

        if baseline_ttg > 0 and current_ttg > baseline_ttg * TTG_INCREASE_FACTOR:
            return [
                RegressionRecord(
                    indicator=RegressionIndicator.RI_04,
                    description=(
                        f"Time-to-green increased {current_ttg / baseline_ttg:.1f}x "
                        f"({baseline_ttg:.0f}ms → {current_ttg:.0f}ms)"
                    ),
                    metric_id=MetricId.M_02,
                    previous_value=baseline_ttg,
                    current_value=current_ttg,
                    severity=_INDICATOR_SEVERITY[RegressionIndicator.RI_04],
                )
            ]
        return []


class RegressionRecorder:
    """In-memory storage for regression records with triage tracking."""

    def __init__(self) -> None:
        self._records: dict[str, RegressionRecord] = {}

    def record(self, regression: RegressionRecord) -> RegressionRecord:
        """Store a regression record."""
        self._records[regression.regression_id] = regression
        return regression

    def record_many(self, regressions: list[RegressionRecord]) -> int:
        """Store multiple regression records. Returns count stored."""
        for r in regressions:
            self._records[r.regression_id] = r
        return len(regressions)

    def get(self, regression_id: str) -> RegressionRecord | None:
        """Get a regression by ID."""
        return self._records.get(regression_id)

    def list_all(
        self,
        status: TriageStatus | None = None,
        severity: RegressionSeverity | None = None,
        limit: int = 100,
    ) -> list[RegressionRecord]:
        """List regressions with optional filters."""
        results = list(self._records.values())
        if status is not None:
            results = [r for r in results if r.triage_status == status]
        if severity is not None:
            results = [r for r in results if r.severity == severity]
        results.sort(key=lambda r: r.detected_at, reverse=True)
        return results[:limit]

    def update_triage(
        self,
        regression_id: str,
        status: TriageStatus,
        assignee: str = "",
    ) -> RegressionRecord | None:
        """Update triage status for a regression."""
        record = self._records.get(regression_id)
        if record is None:
            return None
        record.triage_status = status
        if assignee:
            record.assignee = assignee
        return record

    def resolve(
        self,
        regression_id: str,
        resolved_by: str = "",
        fix_commit: str = "",
    ) -> RegressionRecord | None:
        """Mark a regression as resolved."""
        from datetime import UTC, datetime

        record = self._records.get(regression_id)
        if record is None:
            return None
        record.triage_status = TriageStatus.RESOLVED
        record.resolved_by = resolved_by
        record.fix_commit = fix_commit
        record.resolved_at = datetime.now(UTC)
        return record
