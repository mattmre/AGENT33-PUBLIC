"""In-memory outcomes service with optional SQLite persistence (P72)."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from agent33.outcomes.models import (
    FailureModeStat,
    OutcomeDashboard,
    OutcomeEvent,
    OutcomeEventCreate,
    OutcomeMetricType,
    OutcomeSummary,
    OutcomeTrend,
    TrendDirection,
    WeekOverWeekStat,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from agent33.outcomes.persistence import OutcomePersistence

_MAX_EVENTS_PER_TENANT = 10_000


class OutcomesService:
    """Store tenant-scoped outcome events and derive trend views."""

    def __init__(self, *, persistence: OutcomePersistence | None = None) -> None:
        self._events: dict[str, OutcomeEvent] = {}
        self._persistence = persistence

    def record_event(self, *, tenant_id: str, event: OutcomeEventCreate) -> OutcomeEvent:
        """Record an outcome event under a tenant."""
        created = OutcomeEvent(
            tenant_id=tenant_id,
            domain=event.domain,
            event_type=event.event_type,
            metric_type=event.metric_type,
            value=event.value,
            occurred_at=event.occurred_at or datetime.now(UTC),
            metadata=dict(event.metadata),
        )
        self._events[created.id] = created
        if self._persistence is not None:
            self._persistence.save_event(created)
        self._evict_oldest(tenant_id)
        return created

    def list_events(
        self,
        *,
        tenant_id: str,
        domain: str | None = None,
        event_type: str | None = None,
        metric_type: OutcomeMetricType | None = None,
        limit: int = 50,
    ) -> list[OutcomeEvent]:
        """List tenant-scoped events with optional domain/event/metric filters."""
        events = self._filter_events(
            tenant_id=tenant_id,
            domain=domain,
            event_type=event_type,
            metric_type=metric_type,
        )
        events.sort(key=lambda item: item.occurred_at, reverse=True)
        return events[: max(limit, 0)]

    def compute_trend(
        self,
        *,
        tenant_id: str,
        metric_type: OutcomeMetricType,
        domain: str | None = None,
        window: int = 20,
    ) -> OutcomeTrend:
        """Compute trend direction for metric/domain over the requested window."""
        events = self._filter_events(
            tenant_id=tenant_id,
            domain=domain,
            metric_type=metric_type,
        )
        events.sort(key=lambda item: item.occurred_at)
        window = max(window, 1)
        values = [item.value for item in events[-window:]]

        if len(values) < 2:
            previous_avg = values[-1] if values else 0.0
            current_avg = previous_avg
            direction = TrendDirection.STABLE
        else:
            midpoint = len(values) // 2
            previous = values[:midpoint]
            current = values[midpoint:]
            previous_avg = sum(previous) / len(previous)
            current_avg = sum(current) / len(current)
            direction = self._compute_direction(metric_type, previous_avg, current_avg)

        return OutcomeTrend(
            metric_type=metric_type,
            domain=domain or "all",
            window=window,
            direction=direction,
            sample_size=len(values),
            values=values,
            previous_avg=previous_avg,
            current_avg=current_avg,
        )

    def get_dashboard(
        self,
        *,
        tenant_id: str,
        domain: str | None = None,
        window: int = 20,
        recent_limit: int = 10,
    ) -> OutcomeDashboard:
        """Return dashboard payload with trends, recent events, summary, WoW, and failures."""
        filtered = self._filter_events(tenant_id=tenant_id, domain=domain)
        recent_events = sorted(filtered, key=lambda item: item.occurred_at, reverse=True)[
            : max(recent_limit, 0)
        ]

        metric_counts: dict[str, int] = {}
        for metric in OutcomeMetricType:
            metric_counts[metric.value] = len(
                [item for item in filtered if item.metric_type == metric]
            )

        summary = OutcomeSummary(
            total_events=len(filtered),
            domains=sorted({item.domain for item in filtered}),
            event_types=sorted({item.event_type for item in filtered}),
            metric_counts=metric_counts,
        )

        trends = [
            self.compute_trend(
                tenant_id=tenant_id,
                metric_type=metric,
                domain=domain,
                window=window,
            )
            for metric in OutcomeMetricType
        ]

        # --- Week-over-week comparison (P72) ---
        wow = self._compute_week_over_week(tenant_id=tenant_id, domain=domain)

        # --- Top failure modes (P72) ---
        failure_modes = self._compute_top_failure_modes(tenant_id=tenant_id, domain=domain)

        return OutcomeDashboard(
            trends=trends,
            recent_events=recent_events,
            summary=summary,
            week_over_week=wow,
            top_failure_modes=failure_modes,
        )

    def load_historical(
        self,
        tenant_id: str,
        since: datetime | None = None,
        *,
        until: datetime | None = None,
        domain: str | None = None,
        metric_types: Sequence[OutcomeMetricType] | None = None,
        limit: int | None = None,
    ) -> list[OutcomeEvent]:
        """Merge in-memory events with loaded historical events (dedup by ID).

        Returns all events for the tenant, newest first.
        """
        merged: dict[str, OutcomeEvent] = {}
        metric_type_set = set(metric_types) if metric_types is not None else None
        if self._persistence is not None:
            for ev in self._persistence.load_events(
                tenant_id=tenant_id,
                since=since,
                until=until,
                domain=domain,
                metric_types=metric_types,
                limit=limit,
            ):
                merged[ev.id] = ev
        # In-memory events override DB rows if IDs collide
        for ev in self._events.values():
            if ev.tenant_id != tenant_id:
                continue
            if since is not None and ev.occurred_at < since:
                continue
            if until is not None and ev.occurred_at > until:
                continue
            if domain is not None and ev.domain != domain:
                continue
            if metric_type_set is not None and ev.metric_type not in metric_type_set:
                continue
            merged[ev.id] = ev
        result = list(merged.values())
        result.sort(key=lambda item: item.occurred_at, reverse=True)
        if limit is not None:
            return result[: max(limit, 0)]
        return result

    def compute_roi(
        self,
        *,
        tenant_id: str,
        domain: str,
        hours_saved_per_success: float,
        cost_per_hour_usd: float,
        window_days: int = 30,
    ) -> dict[str, float | int]:
        """Compute ROI estimate for a given domain over a time window."""
        since = datetime.now(UTC) - timedelta(days=window_days)
        domain_events = self.load_historical(tenant_id, since=since, domain=domain)

        success_events = [
            ev for ev in domain_events if ev.metric_type == OutcomeMetricType.SUCCESS_RATE
        ]
        total_invocations = len(success_events)
        success_count = sum(1 for ev in success_events if ev.value >= 1.0)
        failure_count = total_invocations - success_count

        latency_events = [
            ev for ev in domain_events if ev.metric_type == OutcomeMetricType.LATENCY_MS
        ]
        avg_latency_ms = (
            sum(ev.value for ev in latency_events) / len(latency_events) if latency_events else 0.0
        )

        estimated_hours_saved = success_count * hours_saved_per_success
        estimated_value_usd = estimated_hours_saved * cost_per_hour_usd
        success_rate = success_count / total_invocations if total_invocations > 0 else 0.0

        return {
            "total_invocations": total_invocations,
            "success_count": success_count,
            "failure_count": failure_count,
            "estimated_hours_saved": round(estimated_hours_saved, 2),
            "estimated_value_usd": round(estimated_value_usd, 2),
            "success_rate": round(success_rate, 4),
            "avg_latency_ms": round(avg_latency_ms, 2),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_week_over_week(
        self, *, tenant_id: str, domain: str | None = None
    ) -> list[WeekOverWeekStat]:
        """Compute current-week vs previous-week average per numeric metric."""
        now = datetime.now(UTC)
        fourteen_days_ago = now - timedelta(days=14)
        seven_days_ago = now - timedelta(days=7)

        all_events = self.load_historical(
            tenant_id,
            since=fourteen_days_ago,
            domain=domain,
        )

        numeric_metrics = [
            OutcomeMetricType.SUCCESS_RATE,
            OutcomeMetricType.QUALITY_SCORE,
            OutcomeMetricType.LATENCY_MS,
            OutcomeMetricType.COST_USD,
        ]
        stats: list[WeekOverWeekStat] = []
        for metric in numeric_metrics:
            metric_events = [ev for ev in all_events if ev.metric_type == metric]
            prev_values = [ev.value for ev in metric_events if ev.occurred_at < seven_days_ago]
            curr_values = [ev.value for ev in metric_events if ev.occurred_at >= seven_days_ago]
            prev_avg = sum(prev_values) / len(prev_values) if prev_values else 0.0
            curr_avg = sum(curr_values) / len(curr_values) if curr_values else 0.0
            pct_change = ((curr_avg - prev_avg) / prev_avg * 100) if prev_avg != 0 else 0.0
            stats.append(
                WeekOverWeekStat(
                    metric_type=metric,
                    current_week_avg=round(curr_avg, 4),
                    previous_week_avg=round(prev_avg, 4),
                    pct_change=round(pct_change, 2),
                )
            )
        return stats

    def _compute_top_failure_modes(
        self, *, tenant_id: str, domain: str | None = None, top_n: int = 10
    ) -> list[FailureModeStat]:
        """Aggregate FAILURE_CLASS events by metadata['failure_class']."""
        events = self._filter_events(
            tenant_id=tenant_id,
            domain=domain,
            metric_type=OutcomeMetricType.FAILURE_CLASS,
        )
        counter: Counter[str] = Counter()
        for ev in events:
            fc = ev.metadata.get("failure_class", "unknown")
            if isinstance(fc, str):
                counter[fc] += 1
            else:
                counter["unknown"] += 1
        return [
            FailureModeStat(failure_class=cls, count=cnt)
            for cls, cnt in counter.most_common(top_n)
        ]

    def _evict_oldest(self, tenant_id: str) -> None:
        """Cap in-memory events at _MAX_EVENTS_PER_TENANT per tenant."""
        tenant_events = [
            (eid, ev) for eid, ev in self._events.items() if ev.tenant_id == tenant_id
        ]
        if len(tenant_events) <= _MAX_EVENTS_PER_TENANT:
            return
        # Sort by occurred_at ascending (oldest first)
        tenant_events.sort(key=lambda pair: pair[1].occurred_at)
        excess = len(tenant_events) - _MAX_EVENTS_PER_TENANT
        for eid, _ in tenant_events[:excess]:
            del self._events[eid]

    def _filter_events(
        self,
        *,
        tenant_id: str,
        domain: str | None = None,
        event_type: str | None = None,
        metric_type: OutcomeMetricType | None = None,
    ) -> list[OutcomeEvent]:
        events = [item for item in self._events.values() if item.tenant_id == tenant_id]
        if domain is not None:
            events = [item for item in events if item.domain == domain]
        if event_type is not None:
            events = [item for item in events if item.event_type == event_type]
        if metric_type is not None:
            events = [item for item in events if item.metric_type == metric_type]
        return events

    def health_check(self, *, alert_threshold_hours: float = 24.0) -> dict[str, object]:
        """Return P68-Lite monitoring health status.

        Returns ``{"status": "ok"}`` when at least one event exists whose
        ``occurred_at`` is within *alert_threshold_hours* of now.  Returns
        ``{"status": "stale", "hours_since_last_event": N}`` when the most
        recent event across **all** tenants is older than the threshold, and
        ``{"status": "stale", "hours_since_last_event": null}`` when the
        table has never received any events.
        """
        now = datetime.now(UTC)
        most_recent = max(self._events.values(), key=lambda ev: ev.occurred_at, default=None)
        if self._persistence is not None:
            persisted_recent = self._persistence.load_most_recent_event()
            if persisted_recent is not None and (
                most_recent is None or persisted_recent.occurred_at > most_recent.occurred_at
            ):
                most_recent = persisted_recent
        if most_recent is None:
            return {"status": "stale", "hours_since_last_event": None}
        delta_hours = (now - most_recent.occurred_at).total_seconds() / 3600.0

        if delta_hours <= alert_threshold_hours:
            return {"status": "ok"}
        return {"status": "stale", "hours_since_last_event": round(delta_hours, 2)}

    @staticmethod
    def _compute_direction(
        metric_type: OutcomeMetricType, previous_avg: float, current_avg: float
    ) -> TrendDirection:
        delta = current_avg - previous_avg
        if metric_type in {OutcomeMetricType.LATENCY_MS, OutcomeMetricType.COST_USD}:
            delta = -delta

        baseline = abs(previous_avg) or 1.0
        ratio = delta / baseline
        if ratio > 0.05:
            return TrendDirection.IMPROVING
        if ratio < -0.05:
            return TrendDirection.DECLINING
        return TrendDirection.STABLE
