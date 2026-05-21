"""Alert rules and evaluation against metrics."""

from __future__ import annotations

import operator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from agent33.observability.metrics import MetricsCollector

_COMPARATORS: dict[str, Callable[[float, float], bool]] = {
    "gt": operator.gt,
    "lt": operator.lt,
    "eq": operator.eq,
}


@dataclass
class AlertRule:
    """Definition of an alert condition."""

    name: str
    metric: str
    threshold: float
    comparator: str  # "gt", "lt", or "eq"
    statistic: str = "value"  # "value", "count", "sum", "avg", "min", "max"


@dataclass
class Alert:
    """A triggered alert."""

    rule_name: str
    metric: str
    current_value: float
    threshold: float
    triggered_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class AlertManager:
    """Evaluates alert rules against collected metrics."""

    def __init__(self, metrics: MetricsCollector) -> None:
        self._metrics = metrics
        self._rules: list[AlertRule] = []

    def add_rule(
        self,
        name: str,
        metric: str,
        threshold: float,
        comparator: str = "gt",
        statistic: str = "value",
    ) -> None:
        """Register a new alert rule."""
        if comparator not in _COMPARATORS:
            raise ValueError(f"Unknown comparator: {comparator}. Use gt, lt, or eq.")
        if statistic not in {"value", "count", "sum", "avg", "min", "max"}:
            raise ValueError("Unknown statistic. Use value, count, sum, avg, min, or max.")
        self._rules.append(
            AlertRule(
                name=name,
                metric=metric,
                threshold=threshold,
                comparator=comparator,
                statistic=statistic,
            )
        )

    @staticmethod
    def _extract_value(metric_value: object, statistic: str) -> float | None:
        if isinstance(metric_value, (int, float)):
            return float(metric_value)
        if isinstance(metric_value, dict):
            # Observation summaries expose keys like count/sum/avg/min/max.
            if statistic in metric_value:
                stat_value = metric_value.get(statistic)
                if isinstance(stat_value, (int, float)):
                    return float(stat_value)
            if statistic == "value":
                count_value = metric_value.get("count")
                if isinstance(count_value, (int, float)):
                    return float(count_value)
            # Labelled counters expose {"label=v": count}. For "value" use max label value.
            numeric_values = [v for v in metric_value.values() if isinstance(v, (int, float))]
            if statistic == "value" and numeric_values:
                return float(max(numeric_values))
        return None

    def check_all(self) -> list[Alert]:
        """Evaluate all rules and return triggered alerts."""
        summary = self._metrics.get_summary()
        triggered: list[Alert] = []

        for rule in self._rules:
            metric_value = summary.get(rule.metric)
            if metric_value is None:
                continue
            value = self._extract_value(metric_value, rule.statistic)
            if value is None:
                continue
            compare_fn = _COMPARATORS[rule.comparator]
            if compare_fn(value, rule.threshold):
                triggered.append(
                    Alert(
                        rule_name=rule.name,
                        metric=rule.metric,
                        current_value=float(value),
                        threshold=rule.threshold,
                    )
                )

        return triggered
