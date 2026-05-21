"""In-memory metrics collection."""

from __future__ import annotations

import dataclasses
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent33.llm.pricing import PricingCatalog
    from agent33.services.orchestration_state import OrchestrationStateStore

logger = logging.getLogger(__name__)


@dataclass
class _TimestampedValue:
    """A single observation with a timestamp for rolling-window support."""

    timestamp: float
    value: float


@dataclass
class _Observation:
    values: list[_TimestampedValue] = field(default_factory=list)


class MetricsCollector:
    """Tracks counters and observations for key metrics.

    Observations are stored with timestamps to support rolling-window
    statistics in addition to lifetime aggregates.  The window size is
    configurable via ``window_seconds`` (default 300 = 5 minutes).
    """

    _PROMETHEUS_COUNTER_ALLOWLIST = frozenset(
        {
            "effort_routing_decisions_total",
            "effort_routing_high_effort_total",
            "effort_routing_export_failures_total",
            "http_requests_total",
            "webhook_delivery_total",
            "webhook_delivery_failures_total",
            "dead_letter_queue_captures_total",
            "evaluation_runs_total",
            "evaluation_gate_results_total",
            "connector_health_check_total",
            "connector_message_send_total",
        }
    )
    _PROMETHEUS_OBSERVATION_ALLOWLIST = frozenset(
        {
            "effort_routing_estimated_cost_usd",
            "effort_routing_estimated_token_budget",
            "db_query_duration_seconds",
            "http_request_duration_seconds",
            "health_check_result",
            "webhook_delivery_duration_seconds",
            "dead_letter_queue_depth",
            "evaluation_score",
            "evaluation_duration_seconds",
            "connector_message_send_duration_seconds",
        }
    )

    def __init__(self, *, window_seconds: int = 300) -> None:
        self._counters: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._observations: dict[str, dict[str, _Observation]] = defaultdict(
            lambda: defaultdict(_Observation)
        )
        self.window_seconds = window_seconds

    @staticmethod
    def _label_key(labels: dict[str, str] | None) -> str:
        if not labels:
            return ""
        return ",".join(f"{k}={v}" for k, v in sorted(labels.items()))

    @staticmethod
    def _parse_label_key(label_key: str) -> dict[str, str]:
        labels: dict[str, str] = {}
        if not label_key:
            return labels
        for item in label_key.split(","):
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            labels[key] = value
        return labels

    @staticmethod
    def _escape_label_value(value: str) -> str:
        return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')

    @classmethod
    def _render_prometheus_labels(cls, label_key: str) -> str:
        labels = cls._parse_label_key(label_key)
        if not labels:
            return ""
        rendered = ",".join(
            f'{key}="{cls._escape_label_value(value)}"' for key, value in sorted(labels.items())
        )
        return f"{{{rendered}}}"

    @staticmethod
    def _sanitize_metric_name(name: str) -> str:
        sanitized = re.sub(r"[^a-zA-Z0-9_:]", "_", name)
        if sanitized and sanitized[0].isdigit():
            return f"_{sanitized}"
        return sanitized or "agent33_metric"

    def increment(self, name: str, labels: dict[str, str] | None = None) -> None:
        """Increment a counter by 1."""
        key = self._label_key(labels)
        self._counters[name][key] += 1

    def observe(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """Record an observed value (e.g. latency)."""
        key = self._label_key(labels)
        self._observations[name][key].values.append(
            _TimestampedValue(timestamp=time.time(), value=value)
        )

    def _prune_window(self, obs: _Observation) -> list[_TimestampedValue]:
        """Return entries within the rolling window and prune expired ones.

        Modifies the observation in-place by removing entries older than
        ``self.window_seconds`` and returns the surviving entries.
        """
        cutoff = time.time() - self.window_seconds
        # Partition: entries are appended chronologically, so we can bisect
        # from the left to find the first entry that is within the window.
        surviving: list[_TimestampedValue] = [tv for tv in obs.values if tv.timestamp >= cutoff]
        obs.values[:] = surviving
        return surviving

    def get_summary(self) -> dict[str, Any]:
        """Return a summary of all metrics.

        Each observation entry contains both lifetime statistics (``count``,
        ``sum``, ``avg``, ``min``, ``max``) and rolling-window statistics
        (``window_count``, ``window_sum``, ``window_avg``, ``window_min``,
        ``window_max``).  The lifetime keys preserve backwards compatibility
        with existing consumers such as ``AlertManager``.
        """
        summary: dict[str, Any] = {}

        # Counters
        for name, label_map in self._counters.items():
            if len(label_map) == 1 and "" in label_map:
                summary[name] = label_map[""]
            else:
                summary[name] = dict(label_map)

        # Observations
        cutoff = time.time() - self.window_seconds
        for name, obs_map in self._observations.items():
            for label_key, obs in obs_map.items():
                display = f"{name}({label_key})" if label_key else name
                all_vals = [tv.value for tv in obs.values]
                if all_vals:
                    entry: dict[str, Any] = {
                        # Lifetime stats (backwards-compatible)
                        "count": len(all_vals),
                        "sum": sum(all_vals),
                        "avg": sum(all_vals) / len(all_vals),
                        "min": min(all_vals),
                        "max": max(all_vals),
                    }
                    # Rolling-window stats
                    window_vals = [tv.value for tv in obs.values if tv.timestamp >= cutoff]
                    if window_vals:
                        entry["window_count"] = len(window_vals)
                        entry["window_sum"] = sum(window_vals)
                        entry["window_avg"] = sum(window_vals) / len(window_vals)
                        entry["window_min"] = min(window_vals)
                        entry["window_max"] = max(window_vals)
                    else:
                        entry["window_count"] = 0
                        entry["window_sum"] = 0.0
                        entry["window_avg"] = 0.0
                        entry["window_min"] = 0.0
                        entry["window_max"] = 0.0
                    summary[display] = entry

        return summary

    def render_prometheus(self) -> str:
        """Render a low-cardinality Prometheus exposition payload.

        Includes both lifetime and rolling-window observation gauges.
        Window gauges use a ``_window_`` infix to distinguish them from
        lifetime gauges.
        """
        lines: list[str] = []

        for name in sorted(self._PROMETHEUS_COUNTER_ALLOWLIST):
            label_map = self._counters.get(name)
            if not label_map:
                continue
            metric_name = self._sanitize_metric_name(name)
            lines.append(f"# TYPE {metric_name} counter")
            for label_key, value in sorted(label_map.items()):
                lines.append(f"{metric_name}{self._render_prometheus_labels(label_key)} {value}")

        cutoff = time.time() - self.window_seconds
        for name in sorted(self._PROMETHEUS_OBSERVATION_ALLOWLIST):
            obs_map = self._observations.get(name)
            if not obs_map:
                continue
            metric_name = self._sanitize_metric_name(name)
            # Lifetime TYPE declarations
            lines.extend(
                [
                    f"# TYPE {metric_name}_count gauge",
                    f"# TYPE {metric_name}_sum gauge",
                    f"# TYPE {metric_name}_avg gauge",
                    f"# TYPE {metric_name}_min gauge",
                    f"# TYPE {metric_name}_max gauge",
                ]
            )
            # Rolling-window TYPE declarations
            lines.extend(
                [
                    f"# TYPE {metric_name}_window_count gauge",
                    f"# TYPE {metric_name}_window_avg gauge",
                    f"# TYPE {metric_name}_window_min gauge",
                    f"# TYPE {metric_name}_window_max gauge",
                ]
            )
            for label_key, observation in sorted(obs_map.items()):
                all_values = [tv.value for tv in observation.values]
                if not all_values:
                    continue
                prom_labels = self._render_prometheus_labels(label_key)
                total = sum(all_values)
                count = len(all_values)
                minimum = min(all_values)
                maximum = max(all_values)
                average = total / count
                # Lifetime gauges
                lines.extend(
                    [
                        f"{metric_name}_count{prom_labels} {count}",
                        f"{metric_name}_sum{prom_labels} {total}",
                        f"{metric_name}_avg{prom_labels} {average}",
                        f"{metric_name}_min{prom_labels} {minimum}",
                        f"{metric_name}_max{prom_labels} {maximum}",
                    ]
                )
                # Rolling-window gauges
                window_values = [tv.value for tv in observation.values if tv.timestamp >= cutoff]
                w_count = len(window_values)
                w_avg = (sum(window_values) / w_count) if w_count else 0.0
                w_min = min(window_values) if w_count else 0.0
                w_max = max(window_values) if w_count else 0.0
                lines.extend(
                    [
                        f"{metric_name}_window_count{prom_labels} {w_count}",
                        f"{metric_name}_window_avg{prom_labels} {w_avg}",
                        f"{metric_name}_window_min{prom_labels} {w_min}",
                        f"{metric_name}_window_max{prom_labels} {w_max}",
                    ]
                )

        return "\n".join(lines) + ("\n" if lines else "# no metrics collected\n")


# ---------------------------------------------------------------------------
# CA-060: Dollar-Cost Attribution
# ---------------------------------------------------------------------------

# Legacy pricing per 1K tokens (USD).  Kept for backwards-compatible
# ``CostTracker(pricing={...})`` construction in existing tests.
DEFAULT_MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-4": {"input": 0.03, "output": 0.06},
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
    "claude-3-opus": {"input": 0.015, "output": 0.075},
    "claude-3-sonnet": {"input": 0.003, "output": 0.015},
    "claude-3-haiku": {"input": 0.00025, "output": 0.00125},
}


@dataclass
class CostReport:
    """Summary of costs for a given scope and period."""

    scope: str
    total_cost: float
    input_tokens: int
    output_tokens: int
    invocations: int
    breakdown: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class UsageRecord:
    """A single recorded usage event.

    Previously named ``_UsageRecord``; promoted to public so that
    :meth:`CostTracker.iter_records` can expose a typed iterable.
    """

    model: str
    tokens_in: int
    tokens_out: int
    cost: float
    timestamp: float
    scope: str  # e.g. "workflow:my-wf" or "user:alice"


# Keep a private alias so that any in-repo references to the old name
# (e.g. backdated-record construction in tests) still work.
_UsageRecord = UsageRecord


class CostTracker:
    """Tracks dollar costs per agent invocation, workflow run, and org.

    Pricing resolution order:

    1.  If an explicit ``pricing`` dict is provided (legacy per-1K table),
        use it directly.  This preserves backwards compatibility with
        existing callers and tests.
    2.  Otherwise, delegate to a :class:`~agent33.llm.pricing.PricingCatalog`
        (Phase 49) for model-aware Decimal-precision cost estimation.

    The optional ``provider`` parameter on :meth:`record_usage` is used for
    catalog lookups when available.
    """

    DEFAULT_MAX_RECORDS: int = 100_000

    _NAMESPACE = "usage_metrics"

    def __init__(
        self,
        pricing: dict[str, dict[str, float]] | None = None,
        pricing_catalog: PricingCatalog | None = None,
        max_records: int = DEFAULT_MAX_RECORDS,
        state_store: OrchestrationStateStore | None = None,
    ) -> None:
        self._pricing = pricing  # None means "use catalog"
        self._pricing_catalog = pricing_catalog
        self._records: list[UsageRecord] = []
        self._max_records = max(1, max_records)
        self._state_store = state_store
        if state_store is None:
            logger.warning(
                "cost_tracker_no_state_store: usage records will not persist across restarts"
            )
        self._load_state()

    def _persist_state(self) -> None:
        if self._state_store is None:
            return
        self._state_store.write_namespace(
            self._NAMESPACE,
            {"records": [dataclasses.asdict(r) for r in self._records]},
        )

    def _load_state(self) -> None:
        if self._state_store is None:
            return
        payload = self._state_store.read_namespace(self._NAMESPACE)
        records_data = payload.get("records", [])
        if not isinstance(records_data, list):
            return
        for item in records_data:
            if not isinstance(item, dict):
                continue
            try:
                self._records.append(UsageRecord(**item))
            except Exception as exc:
                logger.warning("usage_record_restore_failed: %s", exc)

    def set_pricing(self, model: str, input_per_1k: float, output_per_1k: float) -> None:
        """Set or update pricing for a model (legacy path)."""
        if self._pricing is None:
            self._pricing = {}
        self._pricing[model] = {"input": input_per_1k, "output": output_per_1k}

    def record_usage(
        self,
        model: str,
        tokens_in: int,
        tokens_out: int,
        scope: str = "global",
        *,
        provider: str = "",
    ) -> float:
        """Record a usage event and return the computed cost.

        Parameters
        ----------
        model:
            Model identifier.
        tokens_in:
            Number of input tokens.
        tokens_out:
            Number of output tokens.
        scope:
            Attribution scope (e.g. ``"workflow:build"``, ``"user:alice"``).
        provider:
            Provider name for PricingCatalog lookup (e.g. ``"openai"``).
            Ignored when an explicit ``pricing`` dict was provided.

        Returns
        -------
        float
            Dollar cost of this invocation.
        """
        cost = self._compute_cost(model, tokens_in, tokens_out, provider)
        self._records.append(
            UsageRecord(
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost=cost,
                timestamp=time.time(),
                scope=scope,
            )
        )
        # FIFO eviction: discard oldest records when the list exceeds the cap.
        overflow = len(self._records) - self._max_records
        if overflow > 0:
            del self._records[:overflow]
        self._persist_state()
        return cost

    def iter_records(
        self,
        scope: str | None = None,
        since: float | None = None,
    ) -> list[UsageRecord]:
        """Return a filtered snapshot of usage records.

        Parameters
        ----------
        scope:
            If provided, only records whose ``scope`` equals *scope* or
            starts with ``scope + ":"`` are included.
        since:
            If provided, only records with ``timestamp >= since`` are included.

        Returns
        -------
        list[UsageRecord]
            Matching records in chronological order (oldest first).
        """
        result: list[UsageRecord] = self._records
        if scope is not None:
            result = [r for r in result if r.scope == scope or r.scope.startswith(scope + ":")]
        if since is not None:
            result = [r for r in result if r.timestamp >= since]
        return result

    def _compute_cost(self, model: str, tokens_in: int, tokens_out: int, provider: str) -> float:
        """Resolve dollar cost via legacy dict or PricingCatalog."""
        # Path 1: explicit pricing dict (legacy / tests)
        if self._pricing is not None:
            prices = self._pricing.get(model, {"input": 0.0, "output": 0.0})
            return (tokens_in / 1000.0) * prices["input"] + (tokens_out / 1000.0) * prices[
                "output"
            ]

        # Path 2: PricingCatalog (Phase 49)
        from agent33.llm.pricing import estimate_cost, get_default_catalog

        catalog = self._pricing_catalog or get_default_catalog()
        result = estimate_cost(
            model, provider or "unknown", tokens_in, tokens_out, catalog=catalog
        )
        return float(result.amount_usd)

    def get_cost(
        self,
        scope: str | None = None,
        period: tuple[float, float] | None = None,
    ) -> CostReport:
        """Get a cost report for the given scope and time period.

        Parameters
        ----------
        scope:
            Filter by scope prefix. ``None`` means all scopes.
        period:
            ``(start_timestamp, end_timestamp)`` filter. ``None`` means all time.

        Returns
        -------
        CostReport
        """
        filtered = self._records
        report_scope = scope or "global"

        if scope is not None:
            filtered = [r for r in filtered if r.scope == scope or r.scope.startswith(scope + ":")]

        if period is not None:
            start, end = period
            filtered = [r for r in filtered if start <= r.timestamp <= end]

        total_cost = sum(r.cost for r in filtered)
        total_in = sum(r.tokens_in for r in filtered)
        total_out = sum(r.tokens_out for r in filtered)

        # Build breakdown by model
        by_model: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"cost": 0.0, "tokens_in": 0, "tokens_out": 0, "count": 0}
        )
        for r in filtered:
            entry = by_model[r.model]
            entry["cost"] += r.cost
            entry["tokens_in"] += r.tokens_in
            entry["tokens_out"] += r.tokens_out
            entry["count"] += 1

        breakdown = [{"model": m, **v} for m, v in by_model.items()]

        return CostReport(
            scope=report_scope,
            total_cost=round(total_cost, 6),
            input_tokens=total_in,
            output_tokens=total_out,
            invocations=len(filtered),
            breakdown=breakdown,
        )
