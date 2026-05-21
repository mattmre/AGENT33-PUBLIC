"""Tests for S18: Phase 31 Analytics Dashboards.

Covers: analytics service methods, response models, metrics snapshot
persistence, max cap enforcement, and API route integration.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from agent33.improvement.analytics import AnalyticsService
from agent33.improvement.models import (
    ChecklistPeriod,
    ImprovementMetric,
    IntakeStatus,
    LearningSignal,
    LearningSignalSeverity,
    LearningSignalType,
    LessonAction,
    LessonActionStatus,
    LessonEventType,
    LessonLearned,
    MetricsSnapshot,
    RefreshScope,
    ResearchIntake,
    RoadmapRefresh,
)
from agent33.improvement.persistence import InMemoryLearningSignalStore
from agent33.improvement.service import ImprovementService
from agent33.main import app
from agent33.security.auth import create_access_token

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def svc() -> ImprovementService:
    return ImprovementService(max_metrics_snapshots=100)


@pytest.fixture()
def analytics(svc: ImprovementService) -> AnalyticsService:
    return AnalyticsService(svc)


@pytest.fixture()
def _reset_routes():
    """Reset the singleton route service to a fresh in-memory instance for each test."""
    from agent33.api.routes.improvements import _reset_service
    from agent33.config import settings

    original_backend = settings.improvement_learning_persistence_backend
    original_enabled = settings.improvement_learning_enabled
    settings.improvement_learning_persistence_backend = "memory"
    settings.improvement_learning_enabled = True
    _reset_service()
    yield
    _reset_service()
    settings.improvement_learning_persistence_backend = original_backend
    settings.improvement_learning_enabled = original_enabled


def _tenant_client(tenant_id: str = "default") -> TestClient:
    token = create_access_token("analytics-user", scopes=[], tenant_id=tenant_id)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def _admin_client() -> TestClient:
    token = create_access_token("admin-user", scopes=["admin"], tenant_id="default")
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------


def _make_intake(
    svc: ImprovementService,
    *,
    status: IntakeStatus = IntakeStatus.SUBMITTED,
    tenant_id: str = "default",
) -> ResearchIntake:
    """Create an intake and transition it to the desired status."""
    from agent33.improvement.models import IntakeContent

    intake = svc.submit_intake(
        ResearchIntake(
            tenant_id=tenant_id,
            content=IntakeContent(title=f"Test intake ({status.value})"),
        )
    )

    # Walk through transitions to reach target status
    transitions: dict[IntakeStatus, list[IntakeStatus]] = {
        IntakeStatus.SUBMITTED: [],
        IntakeStatus.TRIAGED: [IntakeStatus.TRIAGED],
        IntakeStatus.ANALYZING: [IntakeStatus.TRIAGED, IntakeStatus.ANALYZING],
        IntakeStatus.ACCEPTED: [
            IntakeStatus.TRIAGED,
            IntakeStatus.ANALYZING,
            IntakeStatus.ACCEPTED,
        ],
        IntakeStatus.DEFERRED: [
            IntakeStatus.TRIAGED,
            IntakeStatus.ANALYZING,
            IntakeStatus.DEFERRED,
        ],
        IntakeStatus.REJECTED: [
            IntakeStatus.TRIAGED,
            IntakeStatus.ANALYZING,
            IntakeStatus.REJECTED,
        ],
        IntakeStatus.TRACKED: [
            IntakeStatus.TRIAGED,
            IntakeStatus.ANALYZING,
            IntakeStatus.ACCEPTED,
            IntakeStatus.TRACKED,
        ],
    }
    for step in transitions[status]:
        svc.transition_intake(intake.intake_id, step)
    return intake


def _make_lesson(
    svc: ImprovementService,
    *,
    event_type: LessonEventType = LessonEventType.OBSERVATION,
    actions: list[LessonAction] | None = None,
) -> LessonLearned:
    return svc.record_lesson(
        LessonLearned(
            event_type=event_type,
            what_happened="Something happened",
            actions=actions or [],
        )
    )


_signal_counter = 0


def _make_signal(
    svc: ImprovementService,
    *,
    signal_type: LearningSignalType = LearningSignalType.BUG,
    severity: LearningSignalSeverity = LearningSignalSeverity.MEDIUM,
    quality_score: float = 0.5,
    intake_generated: bool = False,
    tenant_id: str = "default",
) -> LearningSignal:
    global _signal_counter  # noqa: PLW0603
    _signal_counter += 1
    signal = LearningSignal(
        signal_type=signal_type,
        severity=severity,
        summary=f"Signal {signal_type.value} {_signal_counter}",
        quality_score=quality_score,
        tenant_id=tenant_id,
    )
    recorded = svc.record_learning_signal(signal)
    # Override enrichment-computed score and intake flag for deterministic
    # analytics assertions (enrichment recalculates quality from signal
    # structure, not from the value we pass in).
    recorded.quality_score = quality_score
    recorded.intake_generated = intake_generated
    return recorded


# ===========================================================================
# Intake Funnel
# ===========================================================================


class TestIntakeFunnel:
    def test_empty_funnel(self, analytics: AnalyticsService) -> None:
        report = analytics.intake_funnel()
        assert report.total_submitted == 0
        assert len(report.steps) == 5
        for step in report.steps:
            assert step.count == 0
            assert step.conversion_rate == 0.0
        assert report.terminal_counts == {"deferred": 0, "rejected": 0}

    def test_diverse_statuses(self, svc: ImprovementService, analytics: AnalyticsService) -> None:
        # Create intakes at various lifecycle stages
        _make_intake(svc, status=IntakeStatus.SUBMITTED)
        _make_intake(svc, status=IntakeStatus.SUBMITTED)
        _make_intake(svc, status=IntakeStatus.TRIAGED)
        _make_intake(svc, status=IntakeStatus.ANALYZING)
        _make_intake(svc, status=IntakeStatus.ACCEPTED)
        _make_intake(svc, status=IntakeStatus.TRACKED)
        _make_intake(svc, status=IntakeStatus.DEFERRED)
        _make_intake(svc, status=IntakeStatus.REJECTED)

        report = analytics.intake_funnel()

        # Total submitted = all 8 (all went through SUBMITTED)
        assert report.total_submitted == 8

        # Find steps by name
        step_map = {s.step: s for s in report.steps}

        # All 8 reached SUBMITTED
        assert step_map["submitted"].count == 8
        assert step_map["submitted"].conversion_rate == 1.0

        # 6 progressed past SUBMITTED (triaged, analyzing, accepted, tracked,
        # deferred, rejected all reached triaged)
        assert step_map["triaged"].count == 6

        # 5 reached analyzing (analyzing, accepted, tracked, deferred, rejected)
        assert step_map["analyzing"].count == 5

        # 2 reached accepted (accepted, tracked)
        assert step_map["accepted"].count == 2

        # 1 reached tracked
        assert step_map["tracked"].count == 1

        # Terminal counts
        assert report.terminal_counts["deferred"] == 1
        assert report.terminal_counts["rejected"] == 1

    def test_tenant_filter(self, svc: ImprovementService, analytics: AnalyticsService) -> None:
        _make_intake(svc, status=IntakeStatus.TRIAGED, tenant_id="tenant-a")
        _make_intake(svc, status=IntakeStatus.TRIAGED, tenant_id="tenant-b")

        report_a = analytics.intake_funnel(tenant_id="tenant-a")
        assert report_a.total_submitted == 1
        assert report_a.tenant_id == "tenant-a"

    def test_conversion_rates_correct(
        self, svc: ImprovementService, analytics: AnalyticsService
    ) -> None:
        """Verify conversion rates are ratios of reached / total_submitted."""
        _make_intake(svc, status=IntakeStatus.SUBMITTED)
        _make_intake(svc, status=IntakeStatus.TRACKED)

        report = analytics.intake_funnel()
        step_map = {s.step: s for s in report.steps}

        # 2 submitted, 1 tracked
        assert report.total_submitted == 2
        assert step_map["submitted"].conversion_rate == 1.0
        assert step_map["tracked"].conversion_rate == 0.5


# ===========================================================================
# Lesson Action Completion
# ===========================================================================


class TestLessonActionCompletion:
    def test_empty(self, analytics: AnalyticsService) -> None:
        report = analytics.lesson_action_completion()
        assert report.total_lessons == 0
        assert report.total_actions == 0
        assert report.completion_rate == 0.0

    def test_mixed_statuses(self, svc: ImprovementService, analytics: AnalyticsService) -> None:
        _make_lesson(
            svc,
            event_type=LessonEventType.FAILURE,
            actions=[
                LessonAction(description="Fix bug", status=LessonActionStatus.COMPLETED),
                LessonAction(description="Write test", status=LessonActionStatus.PENDING),
                LessonAction(description="Review", status=LessonActionStatus.IN_PROGRESS),
            ],
        )
        _make_lesson(
            svc,
            event_type=LessonEventType.SUCCESS,
            actions=[
                LessonAction(description="Document", status=LessonActionStatus.WONT_FIX),
                LessonAction(description="Ship", status=LessonActionStatus.COMPLETED),
            ],
        )

        report = analytics.lesson_action_completion()
        assert report.total_lessons == 2
        assert report.total_actions == 5
        assert report.completed_actions == 2
        assert report.pending_actions == 1
        assert report.in_progress_actions == 1
        assert report.wont_fix_actions == 1
        assert report.completion_rate == pytest.approx(0.4, abs=0.001)

        # by_event_type breakdown
        assert "failure" in report.by_event_type
        assert report.by_event_type["failure"]["total_actions"] == 3
        assert report.by_event_type["failure"]["completed"] == 1
        assert "success" in report.by_event_type
        assert report.by_event_type["success"]["total_actions"] == 2


# ===========================================================================
# Checklist Completion
# ===========================================================================


class TestChecklistCompletion:
    def test_empty(self, analytics: AnalyticsService) -> None:
        report = analytics.checklist_completion()
        assert report.total_checklists == 0
        assert report.completion_rate == 0.0

    def test_by_period(self, svc: ImprovementService, analytics: AnalyticsService) -> None:
        cl1 = svc.create_checklist(ChecklistPeriod.PER_RELEASE, "v1.0")
        svc.complete_checklist_item(cl1.checklist_id, "CI-01")
        svc.complete_checklist_item(cl1.checklist_id, "CI-02")

        svc.create_checklist(ChecklistPeriod.MONTHLY, "2026-03")

        report = analytics.checklist_completion()
        assert report.total_checklists == 2
        # per_release has 5 items, monthly has 5 items => 10 total
        assert report.total_items == 10
        assert report.completed_items == 2
        assert report.completion_rate == pytest.approx(0.2, abs=0.001)
        assert "per_release" in report.by_period
        assert report.by_period["per_release"]["completed_items"] == 2

        # Filter by period
        report_monthly = analytics.checklist_completion(period="monthly")
        assert report_monthly.total_checklists == 1
        assert report_monthly.completed_items == 0
        assert report_monthly.period == "monthly"


# ===========================================================================
# Signal to Intake Conversion
# ===========================================================================


class TestSignalToIntakeConversion:
    def test_empty(self, analytics: AnalyticsService) -> None:
        report = analytics.signal_to_intake_conversion()
        assert report.total_signals == 0
        assert report.conversion_rate == 0.0

    def test_with_data(self, svc: ImprovementService, analytics: AnalyticsService) -> None:
        _make_signal(
            svc,
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.HIGH,
            quality_score=0.8,
            intake_generated=True,
        )
        _make_signal(
            svc,
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.LOW,
            quality_score=0.3,
        )
        _make_signal(
            svc,
            signal_type=LearningSignalType.FEEDBACK,
            severity=LearningSignalSeverity.MEDIUM,
            quality_score=0.6,
            intake_generated=True,
        )

        report = analytics.signal_to_intake_conversion()
        assert report.total_signals == 3
        assert report.signals_with_intake == 2
        assert report.conversion_rate == pytest.approx(0.6667, abs=0.001)

        # by_signal_type
        assert report.by_signal_type["bug"]["total"] == 2
        assert report.by_signal_type["bug"]["with_intake"] == 1
        assert report.by_signal_type["feedback"]["total"] == 1
        assert report.by_signal_type["feedback"]["with_intake"] == 1

        # by_severity
        assert report.by_severity["high"]["total"] == 1
        assert report.by_severity["high"]["with_intake"] == 1
        assert report.by_severity["low"]["total"] == 1
        assert report.by_severity["low"]["with_intake"] == 0


# ===========================================================================
# Quality Distribution
# ===========================================================================


class TestQualityDistribution:
    def test_empty(self, analytics: AnalyticsService) -> None:
        report = analytics.quality_distribution()
        assert report.total_signals == 0
        assert report.mean == 0.0
        assert report.median == 0.0
        assert report.p75 == 0.0
        assert report.p90 == 0.0

    def test_known_scores(self, svc: ImprovementService, analytics: AnalyticsService) -> None:
        scores = [0.1, 0.25, 0.5, 0.7, 0.9]
        for score in scores:
            _make_signal(svc, quality_score=score)

        report = analytics.quality_distribution(bucket_size=0.5)
        assert report.total_signals == 5
        assert report.mean == pytest.approx(0.49, abs=0.01)
        assert report.median == pytest.approx(0.5, abs=0.01)
        # p75: sorted = [0.1, 0.25, 0.5, 0.7, 0.9], index = round(4*0.75) = 3 => 0.7
        assert report.p75 == pytest.approx(0.7, abs=0.01)
        assert report.p90 == pytest.approx(0.9, abs=0.01)

        # Two buckets with bucket_size=0.5: [0.0, 0.5) and [0.5, 1.0]
        assert len(report.buckets) == 2
        assert report.buckets[0].range_start == 0.0
        assert report.buckets[0].range_end == 0.5
        # 0.1, 0.25 are in [0.0, 0.5) => count 2
        assert report.buckets[0].count == 2
        # 0.5, 0.7, 0.9 are in [0.5, 1.0] => count 3
        assert report.buckets[1].count == 3

    def test_custom_bucket_size(
        self, svc: ImprovementService, analytics: AnalyticsService
    ) -> None:
        for score in [0.05, 0.15, 0.25, 0.35, 0.45]:
            _make_signal(svc, quality_score=score)

        report = analytics.quality_distribution(bucket_size=0.1)
        assert report.bucket_size == 0.1
        assert len(report.buckets) == 10
        # First bucket [0.0, 0.1): count 1 (0.05)
        assert report.buckets[0].count == 1
        # Second bucket [0.1, 0.2): count 1 (0.15)
        assert report.buckets[1].count == 1


# ===========================================================================
# Metrics Time Series
# ===========================================================================


class TestMetricsTimeSeries:
    def test_empty(self, analytics: AnalyticsService) -> None:
        series = analytics.metrics_time_series()
        assert series == []

    def test_extraction(self, svc: ImprovementService, analytics: AnalyticsService) -> None:
        for i in range(3):
            svc.save_metrics_snapshot(
                MetricsSnapshot(
                    period=f"2026-Q{i + 1}",
                    metrics=[
                        ImprovementMetric(
                            metric_id="IM-01",
                            name="Cycle time",
                            unit="hours",
                            current=float(10 + i * 5),
                        ),
                        ImprovementMetric(
                            metric_id="IM-02",
                            name="Rework rate",
                            unit="percent",
                            current=float(20 - i * 3),
                        ),
                    ],
                )
            )

        series = analytics.metrics_time_series()
        assert len(series) == 2  # IM-01 and IM-02

        im01 = next(s for s in series if s.metric_id == "IM-01")
        assert im01.metric_name == "Cycle time"
        assert im01.unit == "hours"
        assert len(im01.points) == 3
        assert im01.points[0].value == 10.0
        assert im01.points[1].value == 15.0
        assert im01.points[2].value == 20.0
        assert im01.points[0].period == "2026-Q1"

    def test_filter_by_metric_id(
        self, svc: ImprovementService, analytics: AnalyticsService
    ) -> None:
        svc.save_metrics_snapshot(
            MetricsSnapshot(
                period="2026-Q1",
                metrics=[
                    ImprovementMetric(
                        metric_id="IM-01", name="Cycle time", unit="hours", current=10.0
                    ),
                    ImprovementMetric(
                        metric_id="IM-02", name="Rework rate", unit="percent", current=20.0
                    ),
                ],
            )
        )

        series = analytics.metrics_time_series(metric_id="IM-02")
        assert len(series) == 1
        assert series[0].metric_id == "IM-02"

    def test_periods_limit(self, svc: ImprovementService, analytics: AnalyticsService) -> None:
        for i in range(10):
            svc.save_metrics_snapshot(
                MetricsSnapshot(
                    period=f"P{i}",
                    metrics=[
                        ImprovementMetric(
                            metric_id="IM-01",
                            name="Cycle time",
                            unit="hours",
                            current=float(i),
                        ),
                    ],
                )
            )

        series = analytics.metrics_time_series(periods=3)
        assert len(series) == 1
        assert len(series[0].points) == 3
        # Should be the last 3 snapshots
        assert series[0].points[0].period == "P7"
        assert series[0].points[2].period == "P9"


# ===========================================================================
# Refresh Cadence
# ===========================================================================


class TestRefreshCadence:
    def test_empty(self, analytics: AnalyticsService) -> None:
        report = analytics.refresh_cadence()
        assert report.total_refreshes == 0
        assert report.completed_refreshes == 0
        assert report.average_days_between is None
        assert report.last_refresh_at is None

    def test_with_completed_refreshes(
        self, svc: ImprovementService, analytics: AnalyticsService
    ) -> None:
        now = datetime.now(UTC)

        r1 = svc.record_refresh(RoadmapRefresh(scope=RefreshScope.MICRO))
        r1.completed_at = now - timedelta(days=20)

        r2 = svc.record_refresh(RoadmapRefresh(scope=RefreshScope.MINOR))
        r2.completed_at = now - timedelta(days=10)

        svc.record_refresh(RoadmapRefresh(scope=RefreshScope.MICRO))
        # Not completed (exercises the incomplete-refresh path)

        report = analytics.refresh_cadence()
        assert report.total_refreshes == 3
        assert report.completed_refreshes == 2
        assert report.average_days_between == pytest.approx(10.0, abs=0.5)
        assert report.last_refresh_at is not None
        assert report.days_since_last_refresh is not None
        assert report.days_since_last_refresh >= 9.0

        # by_scope
        assert report.by_scope["micro"] == 2
        assert report.by_scope["minor"] == 1


# ===========================================================================
# Dashboard Summary
# ===========================================================================


class TestDashboardSummary:
    def test_composition(self, svc: ImprovementService, analytics: AnalyticsService) -> None:
        """Verify dashboard_summary assembles all sub-reports."""
        _make_intake(svc, status=IntakeStatus.TRIAGED)
        _make_lesson(
            svc,
            actions=[LessonAction(description="Do it", status=LessonActionStatus.COMPLETED)],
        )
        _make_signal(svc, quality_score=0.7)
        svc.create_checklist(ChecklistPeriod.MONTHLY, "2026-03")
        svc.record_refresh(RoadmapRefresh(scope=RefreshScope.MICRO))
        svc.save_metrics_snapshot(
            MetricsSnapshot(
                period="2026-Q1",
                metrics=[
                    ImprovementMetric(
                        metric_id="IM-01",
                        name="Cycle time",
                        unit="hours",
                        current=15.0,
                    ),
                ],
            )
        )

        dashboard = analytics.dashboard_summary()
        assert dashboard.intake_funnel.total_submitted == 1
        assert dashboard.lesson_actions.total_lessons == 1
        assert dashboard.lesson_actions.completed_actions == 1
        assert dashboard.checklist_completion.total_checklists == 1
        assert dashboard.signal_to_intake.total_signals == 1
        assert dashboard.quality_distribution.total_signals == 1
        assert dashboard.refresh_cadence.total_refreshes == 1
        assert len(dashboard.metrics_overview) == 1
        assert dashboard.generated_at is not None


# ===========================================================================
# Metrics Snapshot Persistence
# ===========================================================================


class TestMetricsSnapshotPersistence:
    def test_save_and_load_cycle(self) -> None:
        """Verify snapshots survive a save-load round-trip."""
        store = InMemoryLearningSignalStore()
        svc1 = ImprovementService(learning_store=store, max_metrics_snapshots=100)
        svc1.save_metrics_snapshot(
            MetricsSnapshot(
                period="2026-Q1",
                metrics=[
                    ImprovementMetric(
                        metric_id="IM-01",
                        name="Cycle time",
                        unit="hours",
                        current=42.0,
                    ),
                ],
            )
        )
        svc1.save_metrics_snapshot(
            MetricsSnapshot(
                period="2026-Q2",
                metrics=[
                    ImprovementMetric(
                        metric_id="IM-01",
                        name="Cycle time",
                        unit="hours",
                        current=38.0,
                    ),
                ],
            )
        )

        # Create new service from same store to simulate restart
        svc2 = ImprovementService(learning_store=store, max_metrics_snapshots=100)
        snapshots = svc2.list_metrics_snapshots(limit=10)
        assert len(snapshots) == 2
        # newest first
        assert snapshots[0].period == "2026-Q2"
        assert snapshots[0].metrics[0].current == 38.0
        assert snapshots[1].period == "2026-Q1"

    def test_max_snapshots_cap(self) -> None:
        """Verify cap enforcement removes oldest snapshots."""
        store = InMemoryLearningSignalStore()
        svc = ImprovementService(learning_store=store, max_metrics_snapshots=3)

        for i in range(5):
            svc.save_metrics_snapshot(
                MetricsSnapshot(
                    period=f"P{i}",
                    metrics=[
                        ImprovementMetric(
                            metric_id="IM-01",
                            name="Cycle time",
                            unit="hours",
                            current=float(i),
                        ),
                    ],
                )
            )

        snapshots = svc.list_metrics_snapshots(limit=10)
        assert len(snapshots) == 3
        # Should keep only P2, P3, P4 (newest 3)
        periods = [s.period for s in snapshots]
        assert "P2" in periods
        assert "P3" in periods
        assert "P4" in periods
        assert "P0" not in periods
        assert "P1" not in periods

    def test_cap_persists_across_reload(self) -> None:
        """After cap enforcement, reloaded service sees capped count."""
        store = InMemoryLearningSignalStore()
        svc1 = ImprovementService(learning_store=store, max_metrics_snapshots=2)

        for i in range(4):
            svc1.save_metrics_snapshot(
                MetricsSnapshot(
                    period=f"P{i}",
                    metrics=[
                        ImprovementMetric(
                            metric_id="IM-01",
                            name="Cycle time",
                            unit="hours",
                            current=float(i),
                        ),
                    ],
                )
            )

        svc2 = ImprovementService(learning_store=store, max_metrics_snapshots=2)
        assert len(svc2.list_metrics_snapshots(limit=100)) == 2


# ===========================================================================
# Percentile module-level function
# ===========================================================================


class TestPercentileFunction:
    def test_empty(self) -> None:
        from agent33.improvement.metrics import percentile

        assert percentile([], 0.5) == 0.0

    def test_basic(self) -> None:
        from agent33.improvement.metrics import percentile

        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert percentile(values, 0.0) == 1.0
        assert percentile(values, 1.0) == 5.0
        assert percentile(values, 0.5) == 3.0

    def test_service_percentile_delegates(self) -> None:
        """Verify ImprovementService._percentile uses the module function."""
        assert ImprovementService._percentile([10.0, 20.0, 30.0], 0.5) == 20.0


# ===========================================================================
# API Route tests
# ===========================================================================


@pytest.mark.usefixtures("_reset_routes")
class TestAnalyticsRoutes:
    """Integration tests for analytics API endpoints via TestClient."""

    def test_dashboard_returns_200(self) -> None:
        client = _admin_client()
        resp = client.get("/v1/improvements/analytics/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert "intake_funnel" in data
        assert "lesson_actions" in data
        assert "checklist_completion" in data
        assert "signal_to_intake" in data
        assert "quality_distribution" in data
        assert "refresh_cadence" in data
        assert "metrics_overview" in data
        assert "generated_at" in data

    def test_intake_funnel_returns_200(self) -> None:
        client = _admin_client()
        resp = client.get("/v1/improvements/analytics/intake-funnel")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_submitted" in data
        assert "steps" in data
        assert "terminal_counts" in data
        assert len(data["steps"]) == 5

    def test_lesson_actions_returns_200(self) -> None:
        client = _admin_client()
        resp = client.get("/v1/improvements/analytics/lesson-actions")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_lessons" in data
        assert "completion_rate" in data
        assert "by_event_type" in data

    def test_checklist_completion_returns_200(self) -> None:
        client = _admin_client()
        resp = client.get("/v1/improvements/analytics/checklist-completion")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_checklists" in data
        assert "completion_rate" in data

    def test_checklist_completion_invalid_period(self) -> None:
        client = _admin_client()
        resp = client.get(
            "/v1/improvements/analytics/checklist-completion",
            params={"period": "invalid_period"},
        )
        assert resp.status_code == 400

    def test_signal_intake_conversion_returns_200(self) -> None:
        client = _admin_client()
        resp = client.get("/v1/improvements/analytics/signal-intake-conversion")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_signals" in data
        assert "conversion_rate" in data

    def test_quality_distribution_returns_200(self) -> None:
        client = _admin_client()
        resp = client.get("/v1/improvements/analytics/quality-distribution")
        assert resp.status_code == 200
        data = resp.json()
        assert "buckets" in data
        assert "mean" in data
        assert "median" in data
        assert "p75" in data
        assert "p90" in data

    def test_quality_distribution_invalid_bucket_size(self) -> None:
        client = _admin_client()
        resp = client.get(
            "/v1/improvements/analytics/quality-distribution",
            params={"bucket_size": 0.001},
        )
        assert resp.status_code == 422  # FastAPI validation error

    def test_quality_distribution_max_bucket_size(self) -> None:
        client = _admin_client()
        resp = client.get(
            "/v1/improvements/analytics/quality-distribution",
            params={"bucket_size": 0.6},
        )
        assert resp.status_code == 422

    def test_metrics_timeseries_returns_200(self) -> None:
        client = _admin_client()
        resp = client.get("/v1/improvements/analytics/metrics-timeseries")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_refresh_cadence_returns_200(self) -> None:
        client = _admin_client()
        resp = client.get("/v1/improvements/analytics/refresh-cadence")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_refreshes" in data
        assert "completed_refreshes" in data

    def test_dashboard_with_data(self) -> None:
        """Verify dashboard returns populated data after recording entities."""
        client = _admin_client()

        # Create some data via API
        client.post(
            "/v1/improvements/intakes",
            json={"title": "Test Intake", "summary": "For analytics"},
        )
        client.post(
            "/v1/improvements/lessons",
            json={
                "what_happened": "Test event",
                "event_type": "observation",
                "actions": [{"description": "Do something"}],
            },
        )

        resp = client.get("/v1/improvements/analytics/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert data["intake_funnel"]["total_submitted"] >= 1
        assert data["lesson_actions"]["total_lessons"] >= 1
        assert data["lesson_actions"]["total_actions"] >= 1

    def test_metrics_timeseries_with_data(self) -> None:
        """Verify metrics time series returns data after saving snapshots."""
        client = _admin_client()

        # Save two snapshots
        for i in range(2):
            client.post(
                "/v1/improvements/metrics/snapshot",
                json={
                    "period": f"2026-Q{i + 1}",
                    "metrics": [
                        {
                            "metric_id": "IM-01",
                            "name": "Cycle time",
                            "unit": "hours",
                            "current": 10.0 + i * 5,
                        }
                    ],
                },
            )

        resp = client.get("/v1/improvements/analytics/metrics-timeseries")
        assert resp.status_code == 200
        series = resp.json()
        assert len(series) >= 1
        im01_series = [s for s in series if s["metric_id"] == "IM-01"]
        assert len(im01_series) == 1
        assert len(im01_series[0]["points"]) == 2
        assert im01_series[0]["points"][0]["value"] == 10.0

    def test_tenant_scoped_routes(self) -> None:
        """Non-admin users see only their tenant's data."""
        client = _tenant_client("tenant-x")

        resp = client.get("/v1/improvements/analytics/intake-funnel")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tenant_id"] == "tenant-x"

    def test_learning_disabled_blocks_signal_routes(self) -> None:
        """Signal-dependent analytics return 404 when learning is disabled."""
        from agent33.config import settings

        original = settings.improvement_learning_enabled
        try:
            settings.improvement_learning_enabled = False
            client = _admin_client()

            # These endpoints call _ensure_learning_enabled()
            for path in [
                "/v1/improvements/analytics/dashboard",
                "/v1/improvements/analytics/signal-intake-conversion",
                "/v1/improvements/analytics/quality-distribution",
            ]:
                resp = client.get(path)
                assert resp.status_code == 404, f"Expected 404 for {path}"
        finally:
            settings.improvement_learning_enabled = original
