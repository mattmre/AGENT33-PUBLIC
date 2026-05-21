"""Analytics dashboards for the continuous improvement subsystem."""

from __future__ import annotations

import logging
import statistics
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agent33.improvement.metrics import compute_trend, percentile
from agent33.improvement.models import (
    ChecklistCompletionReport,
    DashboardSummary,
    IntakeFunnelReport,
    IntakeFunnelStep,
    IntakeStatus,
    LessonActionCompletionReport,
    MetricsTimeSeries,
    MetricsTimeSeriesPoint,
    QualityBucket,
    QualityDistribution,
    RefreshCadenceReport,
    SignalToIntakeReport,
)

if TYPE_CHECKING:
    from agent33.improvement.service import ImprovementService

logger = logging.getLogger(__name__)

# Funnel stages in lifecycle order (terminal exits counted separately)
_FUNNEL_STAGES: list[IntakeStatus] = [
    IntakeStatus.SUBMITTED,
    IntakeStatus.TRIAGED,
    IntakeStatus.ANALYZING,
    IntakeStatus.ACCEPTED,
    IntakeStatus.TRACKED,
]

_TERMINAL_STATUSES: list[IntakeStatus] = [
    IntakeStatus.DEFERRED,
    IntakeStatus.REJECTED,
]


class AnalyticsService:
    """Pure-read analytics over ImprovementService data.

    All methods are side-effect-free and return freshly constructed report
    models.
    """

    def __init__(self, improvement_service: ImprovementService) -> None:
        self._svc = improvement_service

    # ------------------------------------------------------------------
    # Intake funnel
    # ------------------------------------------------------------------

    def intake_funnel(self, tenant_id: str | None = None) -> IntakeFunnelReport:
        """Count intakes at each lifecycle stage with conversion rates."""
        intakes = self._svc.all_intakes(tenant_id=tenant_id)

        # Count per status
        status_counts: dict[str, int] = {}
        for intake in intakes:
            status_val = intake.disposition.status.value
            status_counts[status_val] = status_counts.get(status_val, 0) + 1

        # Also count intakes that were at SUBMITTED but moved on — they are in
        # later stages now.  The funnel counts how many *reached* a stage.
        # We compute cumulative from the end.
        reached: dict[str, int] = {}
        cumulative = 0
        for stage in reversed(_FUNNEL_STAGES):
            cumulative += status_counts.get(stage.value, 0)
            reached[stage.value] = cumulative
        # Terminal exits are also part of cumulative count up to ANALYZING
        for ts in _TERMINAL_STATUSES:
            reached[IntakeStatus.ANALYZING.value] = reached.get(
                IntakeStatus.ANALYZING.value, 0
            ) + status_counts.get(ts.value, 0)
            # They also reached TRIAGED and SUBMITTED
            reached[IntakeStatus.TRIAGED.value] = reached.get(
                IntakeStatus.TRIAGED.value, 0
            ) + status_counts.get(ts.value, 0)
            reached[IntakeStatus.SUBMITTED.value] = reached.get(
                IntakeStatus.SUBMITTED.value, 0
            ) + status_counts.get(ts.value, 0)

        real_total_submitted = reached.get(IntakeStatus.SUBMITTED.value, 0)

        steps: list[IntakeFunnelStep] = []
        for stage in _FUNNEL_STAGES:
            count = reached.get(stage.value, 0)
            rate = (count / real_total_submitted) if real_total_submitted > 0 else 0.0
            steps.append(
                IntakeFunnelStep(
                    step=stage.value,
                    count=count,
                    conversion_rate=round(rate, 4),
                )
            )

        terminal_counts = {ts.value: status_counts.get(ts.value, 0) for ts in _TERMINAL_STATUSES}

        return IntakeFunnelReport(
            tenant_id=tenant_id,
            total_submitted=real_total_submitted,
            steps=steps,
            terminal_counts=terminal_counts,
        )

    # ------------------------------------------------------------------
    # Lesson action completion
    # ------------------------------------------------------------------

    def lesson_action_completion(self) -> LessonActionCompletionReport:
        """Aggregate action completion across all lessons."""
        lessons = self._svc.all_lessons()
        total_actions = 0
        completed = 0
        pending = 0
        in_progress = 0
        wont_fix = 0
        by_event_type: dict[str, dict[str, int]] = {}

        for lesson in lessons:
            et = lesson.event_type.value
            if et not in by_event_type:
                by_event_type[et] = {
                    "total_actions": 0,
                    "completed": 0,
                    "pending": 0,
                    "in_progress": 0,
                    "wont_fix": 0,
                }
            for action in lesson.actions:
                total_actions += 1
                by_event_type[et]["total_actions"] += 1
                status = action.status.value
                if status == "completed":
                    completed += 1
                    by_event_type[et]["completed"] += 1
                elif status == "pending":
                    pending += 1
                    by_event_type[et]["pending"] += 1
                elif status == "in_progress":
                    in_progress += 1
                    by_event_type[et]["in_progress"] += 1
                elif status == "wont_fix":
                    wont_fix += 1
                    by_event_type[et]["wont_fix"] += 1

        completion_rate = (completed / total_actions) if total_actions > 0 else 0.0

        return LessonActionCompletionReport(
            total_lessons=len(lessons),
            total_actions=total_actions,
            completed_actions=completed,
            pending_actions=pending,
            in_progress_actions=in_progress,
            wont_fix_actions=wont_fix,
            completion_rate=round(completion_rate, 4),
            by_event_type=by_event_type,
        )

    # ------------------------------------------------------------------
    # Checklist completion
    # ------------------------------------------------------------------

    def checklist_completion(self, period: str | None = None) -> ChecklistCompletionReport:
        """Aggregate checklist item completion across all or filtered checklists."""
        from agent33.improvement.models import ChecklistPeriod

        checklists = self._svc.list_checklists(period=ChecklistPeriod(period) if period else None)
        total_items = 0
        completed_items = 0
        by_period: dict[str, dict[str, int]] = {}

        for checklist in checklists:
            p = checklist.period.value
            if p not in by_period:
                by_period[p] = {"total_items": 0, "completed_items": 0}
            for item in checklist.items:
                total_items += 1
                by_period[p]["total_items"] += 1
                if item.completed:
                    completed_items += 1
                    by_period[p]["completed_items"] += 1

        completion_rate = (completed_items / total_items) if total_items > 0 else 0.0

        return ChecklistCompletionReport(
            period=period,
            total_checklists=len(checklists),
            total_items=total_items,
            completed_items=completed_items,
            completion_rate=round(completion_rate, 4),
            by_period=by_period,
        )

    # ------------------------------------------------------------------
    # Signal to intake conversion
    # ------------------------------------------------------------------

    def signal_to_intake_conversion(self, tenant_id: str | None = None) -> SignalToIntakeReport:
        """Compute signal-to-intake conversion grouped by type and severity."""
        signals = self._svc.all_signals(tenant_id=tenant_id)
        total = len(signals)
        with_intake = 0
        by_signal_type: dict[str, dict[str, int]] = {}
        by_severity: dict[str, dict[str, int]] = {}

        for signal in signals:
            st = signal.signal_type.value
            sev = signal.severity.value
            if st not in by_signal_type:
                by_signal_type[st] = {"total": 0, "with_intake": 0}
            if sev not in by_severity:
                by_severity[sev] = {"total": 0, "with_intake": 0}
            by_signal_type[st]["total"] += 1
            by_severity[sev]["total"] += 1
            if signal.intake_generated:
                with_intake += 1
                by_signal_type[st]["with_intake"] += 1
                by_severity[sev]["with_intake"] += 1

        conversion_rate = (with_intake / total) if total > 0 else 0.0

        return SignalToIntakeReport(
            total_signals=total,
            signals_with_intake=with_intake,
            conversion_rate=round(conversion_rate, 4),
            by_signal_type=by_signal_type,
            by_severity=by_severity,
        )

    # ------------------------------------------------------------------
    # Quality distribution
    # ------------------------------------------------------------------

    def quality_distribution(
        self, tenant_id: str | None = None, bucket_size: float = 0.1
    ) -> QualityDistribution:
        """Build a histogram of signal quality scores with statistics."""
        signals = self._svc.all_signals(tenant_id=tenant_id)
        scores = [s.quality_score for s in signals]
        total = len(scores)

        # Build histogram buckets
        buckets: list[QualityBucket] = []
        if bucket_size > 0:
            start = 0.0
            while start < 1.0:
                end = round(min(start + bucket_size, 1.0), 10)
                count = sum(1 for s in scores if start <= s < end)
                # Include upper boundary for the last bucket
                if end >= 1.0:
                    count = sum(1 for s in scores if start <= s <= end)
                buckets.append(
                    QualityBucket(
                        range_start=round(start, 4),
                        range_end=round(end, 4),
                        count=count,
                    )
                )
                start = end

        if scores:
            mean_val = round(statistics.mean(scores), 4)
            median_val = round(statistics.median(scores), 4)
            p75_val = round(percentile(scores, 0.75), 4)
            p90_val = round(percentile(scores, 0.90), 4)
        else:
            mean_val = 0.0
            median_val = 0.0
            p75_val = 0.0
            p90_val = 0.0

        return QualityDistribution(
            bucket_size=bucket_size,
            buckets=buckets,
            total_signals=total,
            mean=mean_val,
            median=median_val,
            p75=p75_val,
            p90=p90_val,
        )

    # ------------------------------------------------------------------
    # Metrics time series
    # ------------------------------------------------------------------

    def metrics_time_series(
        self, metric_id: str | None = None, periods: int = 8
    ) -> list[MetricsTimeSeries]:
        """Extract chart-ready time series from metrics snapshots."""
        snapshots = self._svc.all_metrics_snapshots()
        # Snapshots are returned newest-first; reverse to chronological order
        snapshots = list(reversed(snapshots))
        if periods > 0:
            snapshots = snapshots[-periods:]

        # Discover all metric IDs across snapshots
        metric_ids: list[str] = []
        metric_meta: dict[str, tuple[str, str]] = {}  # id -> (name, unit)
        for snap in snapshots:
            for m in snap.metrics:
                if m.metric_id not in metric_meta:
                    metric_ids.append(m.metric_id)
                    metric_meta[m.metric_id] = (m.name, m.unit)

        if metric_id is not None:
            metric_ids = [mid for mid in metric_ids if mid == metric_id]

        result: list[MetricsTimeSeries] = []
        for mid in metric_ids:
            name, unit = metric_meta[mid]
            points: list[MetricsTimeSeriesPoint] = []
            values: list[float] = []
            for snap in snapshots:
                for m in snap.metrics:
                    if m.metric_id == mid:
                        points.append(
                            MetricsTimeSeriesPoint(
                                captured_at=snap.captured_at,
                                period=snap.period,
                                value=m.current,
                            )
                        )
                        values.append(m.current)
                        break
            trend = compute_trend(values)
            result.append(
                MetricsTimeSeries(
                    metric_id=mid,
                    metric_name=name,
                    unit=unit,
                    points=points,
                    trend=trend.value,
                )
            )

        return result

    # ------------------------------------------------------------------
    # Refresh cadence
    # ------------------------------------------------------------------

    def refresh_cadence(self) -> RefreshCadenceReport:
        """Compute average gap between completed roadmap refreshes."""
        refreshes = self._svc.all_refreshes()
        total = len(refreshes)
        completed = [r for r in refreshes if r.completed_at is not None]
        completed.sort(key=lambda r: r.completed_at or datetime.min.replace(tzinfo=UTC))

        by_scope: dict[str, int] = {}
        for r in refreshes:
            scope_val = r.scope.value
            by_scope[scope_val] = by_scope.get(scope_val, 0) + 1

        avg_days: float | None = None
        last_refresh_at: datetime | None = None
        days_since: float | None = None

        if completed:
            last_refresh_at = completed[-1].completed_at
            if len(completed) >= 2:
                gaps = []
                for i in range(1, len(completed)):
                    prev_at = completed[i - 1].completed_at
                    curr_at = completed[i].completed_at
                    assert prev_at is not None and curr_at is not None
                    gap = (curr_at - prev_at).total_seconds() / 86400.0
                    gaps.append(gap)
                avg_days = round(statistics.mean(gaps), 2)
            if last_refresh_at is not None:
                days_since = round(
                    (datetime.now(UTC) - last_refresh_at).total_seconds() / 86400.0, 2
                )

        return RefreshCadenceReport(
            total_refreshes=total,
            completed_refreshes=len(completed),
            by_scope=by_scope,
            average_days_between=avg_days,
            last_refresh_at=last_refresh_at,
            days_since_last_refresh=days_since,
        )

    # ------------------------------------------------------------------
    # Dashboard summary (composite)
    # ------------------------------------------------------------------

    def dashboard_summary(
        self,
        tenant_id: str | None = None,
        periods: int = 8,
        bucket_size: float = 0.1,
    ) -> DashboardSummary:
        """Assemble all analytics reports into a single dashboard summary."""
        return DashboardSummary(
            intake_funnel=self.intake_funnel(tenant_id=tenant_id),
            lesson_actions=self.lesson_action_completion(),
            checklist_completion=self.checklist_completion(),
            signal_to_intake=self.signal_to_intake_conversion(tenant_id=tenant_id),
            quality_distribution=self.quality_distribution(
                tenant_id=tenant_id, bucket_size=bucket_size
            ),
            refresh_cadence=self.refresh_cadence(),
            metrics_overview=self.metrics_time_series(periods=periods),
        )
