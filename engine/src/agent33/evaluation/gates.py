"""Regression gate enforcer.

Implements the gating thresholds and gate execution matrix from
``core/arch/REGRESSION_GATES.md``.
"""

from __future__ import annotations

import logging

from agent33.evaluation.golden_tasks import tasks_for_gate
from agent33.evaluation.models import (
    GateAction,
    GateCheckResult,
    GateReport,
    GateResult,
    GateThreshold,
    GateType,
    GoldenTag,
    MetricId,
    TaskResult,
    TaskRunResult,
    ThresholdOperator,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default thresholds (§ Gating Thresholds v1.0.0)
# ---------------------------------------------------------------------------

DEFAULT_THRESHOLDS: list[GateThreshold] = [
    # M-01: Success Rate
    GateThreshold(
        metric_id=MetricId.M_01,
        gate=GateType.G_PR,
        operator=ThresholdOperator.GTE,
        value=80.0,
        action=GateAction.BLOCK,
    ),
    GateThreshold(
        metric_id=MetricId.M_01,
        gate=GateType.G_MRG,
        operator=ThresholdOperator.GTE,
        value=90.0,
        action=GateAction.BLOCK,
    ),
    GateThreshold(
        metric_id=MetricId.M_01,
        gate=GateType.G_REL,
        operator=ThresholdOperator.GTE,
        value=95.0,
        action=GateAction.BLOCK,
    ),
    # M-03: Rework Rate
    GateThreshold(
        metric_id=MetricId.M_03,
        gate=GateType.G_PR,
        operator=ThresholdOperator.LTE,
        value=30.0,
        action=GateAction.WARN,
    ),
    GateThreshold(
        metric_id=MetricId.M_03,
        gate=GateType.G_MRG,
        operator=ThresholdOperator.LTE,
        value=20.0,
        action=GateAction.BLOCK,
    ),
    GateThreshold(
        metric_id=MetricId.M_03,
        gate=GateType.G_REL,
        operator=ThresholdOperator.LTE,
        value=10.0,
        action=GateAction.BLOCK,
    ),
    # M-05: Scope Adherence
    GateThreshold(
        metric_id=MetricId.M_05,
        gate=GateType.G_PR,
        operator=ThresholdOperator.GTE,
        value=90.0,
        action=GateAction.BLOCK,
    ),
    GateThreshold(
        metric_id=MetricId.M_05,
        gate=GateType.G_MRG,
        operator=ThresholdOperator.EQ,
        value=100.0,
        action=GateAction.BLOCK,
    ),
    # M-01: Success Rate (G-MON — relaxed monitoring threshold)
    GateThreshold(
        metric_id=MetricId.M_01,
        gate=GateType.G_MON,
        operator=ThresholdOperator.GTE,
        value=85.0,
        action=GateAction.WARN,
    ),
    # M-03: Rework Rate (G-MON — relaxed monitoring threshold)
    GateThreshold(
        metric_id=MetricId.M_03,
        gate=GateType.G_MON,
        operator=ThresholdOperator.LTE,
        value=25.0,
        action=GateAction.WARN,
    ),
]

# Gate → required golden task tag mapping (§ Gate Execution Matrix)
GATE_REQUIRED_TAGS: dict[GateType, GoldenTag] = {
    GateType.G_PR: GoldenTag.GT_SMOKE,
    GateType.G_MRG: GoldenTag.GT_CRITICAL,
    GateType.G_REL: GoldenTag.GT_RELEASE,
    GateType.G_MON: GoldenTag.GT_OPTIONAL,
}

BLOCKING_GATES = {GateType.G_PR, GateType.G_MRG, GateType.G_REL}


def _check_threshold(threshold: GateThreshold, actual: float) -> bool:
    """Evaluate a threshold comparison."""
    op = threshold.operator
    target = threshold.value
    if op == ThresholdOperator.GTE:
        return actual >= target
    if op == ThresholdOperator.LTE:
        return actual <= target
    if op == ThresholdOperator.EQ:
        return abs(actual - target) < 0.001
    if op == ThresholdOperator.GT:
        return actual > target
    if op == ThresholdOperator.LT:
        return actual < target
    return False  # pragma: no cover


class GateEnforcer:
    """Evaluate metrics and golden task results against gate thresholds."""

    def __init__(self, thresholds: list[GateThreshold] | None = None) -> None:
        self._thresholds = thresholds or DEFAULT_THRESHOLDS

    @property
    def thresholds(self) -> list[GateThreshold]:
        return list(self._thresholds)

    def check_gate(
        self,
        gate: GateType,
        metric_values: dict[MetricId, float],
        task_results: list[TaskRunResult] | None = None,
    ) -> GateReport:
        """Run all threshold checks for the given gate.

        Parameters
        ----------
        gate:
            Which gate to check (G-PR, G-MRG, G-REL, G-MON).
        metric_values:
            Mapping of metric IDs to computed values.
        task_results:
            Golden task results for tag-based golden task gating.
        """
        report = GateReport(gate=gate)

        # Check metric thresholds
        gate_thresholds = [t for t in self._thresholds if t.gate == gate]
        for threshold in gate_thresholds:
            actual = metric_values.get(threshold.metric_id, 0.0)
            passed = _check_threshold(threshold, actual)
            result = GateCheckResult(
                threshold=threshold,
                actual_value=actual,
                passed=passed,
                action_taken=GateAction.BLOCK if not passed else GateAction.WARN,
            )
            report.check_results.append(result)

            if not passed:
                if threshold.action == GateAction.BLOCK:
                    report.overall = GateResult.FAIL
                elif threshold.action == GateAction.WARN and report.overall != GateResult.FAIL:
                    report.overall = GateResult.WARN

        # Check golden task pass requirements
        if task_results is not None:
            report.golden_task_results = list(task_results)
            required_tag = self.get_required_tag(gate)
            required_ids = tasks_for_gate(required_tag) if required_tag is not None else []
            result_by_id = {r.item_id: r for r in task_results}
            report.required_item_ids = required_ids
            report.missing_required_items = [
                item_id for item_id in required_ids if item_id not in result_by_id
            ]
            report.skipped_required_items = [
                item_id
                for item_id in required_ids
                if result_by_id.get(item_id) is not None
                and result_by_id[item_id].result == TaskResult.SKIP
            ]
            report.failed_required_items = [
                item_id
                for item_id in required_ids
                if result_by_id.get(item_id) is not None
                and result_by_id[item_id].result in (TaskResult.FAIL, TaskResult.ERROR)
            ]
            report.failed_extra_items = [
                r.item_id
                for r in task_results
                if r.item_id not in required_ids
                and r.result in (TaskResult.FAIL, TaskResult.ERROR)
            ]

            required_gate_breaches = (
                report.missing_required_items
                + report.skipped_required_items
                + report.failed_required_items
                + report.failed_extra_items
            )
            if required_gate_breaches and gate in BLOCKING_GATES:
                report.overall = GateResult.FAIL
                logger.warning(
                    "gate_failed gate=%s required_items=%d missing=%d skipped=%d "
                    "failed=%d extra_failed=%d",
                    gate.value,
                    len(required_ids),
                    len(report.missing_required_items),
                    len(report.skipped_required_items),
                    len(report.failed_required_items),
                    len(report.failed_extra_items),
                )
            elif required_gate_breaches and report.overall != GateResult.FAIL:
                report.overall = GateResult.WARN

        if report.overall == GateResult.PASS:
            logger.info("gate_passed gate=%s", gate.value)

        return report

    def get_thresholds_for_gate(self, gate: GateType) -> list[GateThreshold]:
        """Return thresholds applicable to the given gate."""
        return [t for t in self._thresholds if t.gate == gate]

    def get_required_tag(self, gate: GateType) -> GoldenTag | None:
        """Return the golden task tag required for this gate."""
        return GATE_REQUIRED_TAGS.get(gate)
