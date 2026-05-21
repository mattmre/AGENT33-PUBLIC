"""Session analytics and insights engine.

Aggregates data from MetricsCollector and CostTracker to produce a
consolidated InsightsReport covering sessions, token usage, cost attribution,
tool/model breakdowns, and daily activity histograms.

Phase 57 -- Hermes Adoption Roadmap.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent33.observability.metrics import CostTracker, MetricsCollector, UsageRecord


@dataclass
class InsightsReport:
    """Consolidated analytics report for a configurable time period."""

    total_sessions: int
    total_tokens: int
    total_cost_usd: Decimal
    avg_session_duration_seconds: float
    tool_usage: dict[str, int]
    model_usage: dict[str, dict[str, Any]]
    daily_activity: list[dict[str, Any]]
    period_days: int
    generated_at: str


class InsightsEngine:
    """Computes analytics from MetricsCollector and CostTracker data.

    Parameters
    ----------
    metrics_collector:
        The in-process metrics collector that holds counters and observations.
    cost_tracker:
        Optional cost tracker for dollar-cost attribution.  When ``None``,
        cost-related fields in the report are zero-valued.
    """

    def __init__(
        self,
        metrics_collector: MetricsCollector,
        cost_tracker: CostTracker | None = None,
    ) -> None:
        self._metrics = metrics_collector
        self._cost_tracker = cost_tracker

    def generate(
        self,
        days: int = 30,
        tenant_id: str | None = None,
    ) -> InsightsReport:
        """Generate an analytics report for the last *days* days.

        Parameters
        ----------
        days:
            Number of days to look back.  Must be >= 1.
        tenant_id:
            Optional tenant filter.  When provided, only cost records
            whose scope starts with ``"tenant:<tenant_id>"`` are included.

        Returns
        -------
        InsightsReport
        """
        if days < 1:
            days = 1

        now = time.time()
        cutoff = now - (days * 86400)
        period = (cutoff, now)

        # -- Sessions & HTTP activity -----------------------------------------
        total_sessions = self._compute_total_sessions()
        avg_duration = self._compute_avg_session_duration()

        # -- Token & cost aggregation from CostTracker -----------------------
        total_tokens = 0
        total_cost = Decimal("0")
        model_usage: dict[str, dict[str, Any]] = {}
        daily_activity: list[dict[str, Any]] = []

        if self._cost_tracker is not None:
            scope_prefix = f"tenant:{tenant_id}" if tenant_id else None
            report = self._cost_tracker.get_cost(scope=scope_prefix, period=period)
            total_tokens = report.input_tokens + report.output_tokens
            total_cost = Decimal(str(report.total_cost))

            # Build model usage breakdown from the cost report breakdown
            for entry in report.breakdown:
                model_name = entry["model"]
                model_tokens = entry["tokens_in"] + entry["tokens_out"]
                model_cost = entry["cost"]
                model_usage[model_name] = {
                    "tokens": model_tokens,
                    "input_tokens": entry["tokens_in"],
                    "output_tokens": entry["tokens_out"],
                    "cost_usd": float(model_cost),
                    "invocations": entry["count"],
                }

            # Build daily activity from CostTracker records
            daily_activity = self._build_daily_activity(
                cutoff=cutoff,
                now=now,
                days=days,
                tenant_id=tenant_id,
            )

        # -- Tool usage from MetricsCollector ---------------------------------
        tool_usage = self._compute_tool_usage()

        return InsightsReport(
            total_sessions=total_sessions,
            total_tokens=total_tokens,
            total_cost_usd=total_cost,
            avg_session_duration_seconds=avg_duration,
            tool_usage=tool_usage,
            model_usage=model_usage,
            daily_activity=daily_activity,
            period_days=days,
            generated_at=datetime.now(tz=UTC).isoformat(),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_total_sessions(self) -> int:
        """Derive total session count from the metrics collector.

        Uses the ``http_requests_total`` counter as a proxy for sessions
        since a dedicated session counter is not yet tracked.
        """
        summary = self._metrics.get_summary()
        raw = summary.get("http_requests_total", 0)
        if isinstance(raw, int):
            return raw
        if isinstance(raw, dict):
            return sum(raw.values())
        return 0

    def _compute_avg_session_duration(self) -> float:
        """Derive average session duration from HTTP request latency.

        Uses the ``http_request_duration_seconds`` observation as a proxy.
        Returns 0.0 if no data is available.
        """
        summary = self._metrics.get_summary()
        duration_entry = summary.get("http_request_duration_seconds")
        if isinstance(duration_entry, dict) and "avg" in duration_entry:
            return float(duration_entry["avg"])
        return 0.0

    def _compute_tool_usage(self) -> dict[str, int]:
        """Extract per-tool execution counts from metrics.

        Tool executions are tracked via counter labels.  Falls back to
        the effort routing counter when tool-level counters are absent.
        """
        summary = self._metrics.get_summary()
        tool_counts: dict[str, int] = {}

        # Check for tool execution counters (labeled by tool name)
        for key, value in summary.items():
            if key.startswith("tool_execution_") and isinstance(value, int):
                tool_name = key.removeprefix("tool_execution_").removesuffix("_total")
                tool_counts[tool_name] = value

        # If no tool-specific counters exist, report effort routing as a proxy
        if not tool_counts:
            effort_total = summary.get("effort_routing_decisions_total", 0)
            if isinstance(effort_total, int) and effort_total > 0:
                tool_counts["effort_routing"] = effort_total
            elif isinstance(effort_total, dict):
                for label, count in effort_total.items():
                    display = f"effort_routing({label})" if label else "effort_routing"
                    tool_counts[display] = count

        return tool_counts

    def _build_daily_activity(
        self,
        cutoff: float,
        now: float,
        days: int,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build per-day session/token histograms from CostTracker records.

        Uses the public :meth:`CostTracker.iter_records` API instead of
        accessing the private ``_records`` list directly.
        """
        if self._cost_tracker is None:
            return []

        scope_prefix = f"tenant:{tenant_id}" if tenant_id else None
        records: list[UsageRecord] = self._cost_tracker.iter_records(
            scope=scope_prefix,
            since=cutoff,
        )

        daily: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"sessions": 0, "tokens": 0, "cost_usd": 0.0}
        )

        for record in records:
            if record.timestamp > now:
                continue
            date_str = datetime.fromtimestamp(record.timestamp, tz=UTC).strftime("%Y-%m-%d")
            daily[date_str]["sessions"] += 1
            daily[date_str]["tokens"] += record.tokens_in + record.tokens_out
            daily[date_str]["cost_usd"] += record.cost

        # Fill gaps so every day in the period has an entry
        result: list[dict[str, Any]] = []
        start_date = datetime.fromtimestamp(cutoff, tz=UTC).date()
        end_date = datetime.fromtimestamp(now, tz=UTC).date()
        current = start_date
        while current <= end_date:
            date_key = current.strftime("%Y-%m-%d")
            entry = daily.get(date_key, {"sessions": 0, "tokens": 0, "cost_usd": 0.0})
            result.append({"date": date_key, **entry})
            current += timedelta(days=1)

        return result
