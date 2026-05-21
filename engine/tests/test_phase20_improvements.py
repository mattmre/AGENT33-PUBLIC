"""Phase 20 — Continuous Improvement & Research Intake tests.

Covers: models, checklists, metrics, service, and API routes.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent33.improvement.checklists import (
    ChecklistEvaluator,
    build_checklist,
)
from agent33.improvement.metrics import (
    MetricsTracker,
    compute_trend,
    default_metrics,
)
from agent33.improvement.models import (
    ChecklistPeriod,
    ImprovementMetric,
    IntakeClassification,
    IntakeContent,
    IntakeRelevance,
    IntakeStatus,
    LessonAction,
    LessonActionStatus,
    LessonEventType,
    LessonLearned,
    MetricsSnapshot,
    MetricTrend,
    RefreshScope,
    ResearchIntake,
    ResearchType,
    ResearchUrgency,
    RoadmapRefresh,
)
from agent33.improvement.service import ImprovementService
from agent33.main import app
from agent33.security.auth import create_access_token

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def service() -> ImprovementService:
    return ImprovementService()


@pytest.fixture()
def _reset_routes():
    """Reset the singleton route service to a fresh in-memory instance for each test."""
    from agent33.api.routes.improvements import _reset_service
    from agent33.config import settings

    original_backend = settings.improvement_learning_persistence_backend
    settings.improvement_learning_persistence_backend = "memory"
    _reset_service()
    yield
    _reset_service()
    settings.improvement_learning_persistence_backend = original_backend


def _tenant_client(tenant_id: str) -> TestClient:
    token = create_access_token("improvements-user", scopes=[], tenant_id=tenant_id)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


# ===========================================================================
# Models
# ===========================================================================


class TestModels:
    """Test data model construction and defaults."""

    def test_research_intake_defaults(self):
        intake = ResearchIntake(
            content=IntakeContent(title="Test Research"),
        )
        assert intake.intake_id.startswith("RI-")
        assert intake.disposition.status == IntakeStatus.SUBMITTED
        assert intake.classification.research_type == ResearchType.EXTERNAL
        assert intake.classification.urgency == ResearchUrgency.MEDIUM

    def test_research_intake_full(self):
        intake = ResearchIntake(
            submitted_by="researcher",
            classification=IntakeClassification(
                research_type=ResearchType.COMPETITIVE,
                category="benchmarks",
                urgency=ResearchUrgency.HIGH,
            ),
            content=IntakeContent(
                title="Competitor Analysis",
                summary="Analysis of competitor features",
                source="https://example.com",
            ),
            relevance=IntakeRelevance(
                impact_areas=["performance", "features"],
                affected_phases=[14, 15],
                priority_score=8,
            ),
        )
        assert intake.classification.research_type == ResearchType.COMPETITIVE
        assert intake.relevance.priority_score == 8
        assert len(intake.relevance.impact_areas) == 2

    def test_lesson_learned_defaults(self):
        lesson = LessonLearned()
        assert lesson.lesson_id.startswith("LL-")
        assert lesson.event_type == LessonEventType.OBSERVATION
        assert lesson.implemented is False

    def test_lesson_learned_with_actions(self):
        lesson = LessonLearned(
            phase="14",
            event_type=LessonEventType.FAILURE,
            what_happened="Build failed due to missing dependency",
            root_cause="Dependency not in requirements",
            actions=[
                LessonAction(
                    description="Add dependency check to CI",
                    owner="devops",
                ),
                LessonAction(
                    description="Update requirements.txt",
                    owner="developer",
                ),
            ],
        )
        assert len(lesson.actions) == 2
        assert lesson.actions[0].status == LessonActionStatus.PENDING

    def test_improvement_metric_defaults(self):
        metric = ImprovementMetric(metric_id="IM-01", name="Cycle time")
        assert metric.trend == MetricTrend.STABLE
        assert metric.baseline == 0.0

    def test_metrics_snapshot(self):
        snap = MetricsSnapshot(
            period="2026-Q1",
            metrics=[
                ImprovementMetric(metric_id="IM-01", name="Cycle time", current=24.5),
            ],
        )
        assert snap.snapshot_id.startswith("MSN-")
        assert len(snap.metrics) == 1

    def test_roadmap_refresh_defaults(self):
        refresh = RoadmapRefresh()
        assert refresh.refresh_id.startswith("RMR-")
        assert refresh.scope == RefreshScope.MICRO
        assert refresh.completed_at is None

    def test_all_enum_values(self):
        """Verify enum membership counts match spec."""
        assert len(ResearchType) == 5
        assert len(IntakeStatus) == 7
        assert len(LessonEventType) == 3
        assert len(LessonActionStatus) == 4
        assert len(MetricTrend) == 3
        assert len(ChecklistPeriod) == 3
        assert len(RefreshScope) == 4


# ===========================================================================
# Checklists
# ===========================================================================


class TestChecklists:
    """Test canonical improvement checklists (CI-01..CI-15)."""

    def test_build_per_release_checklist(self):
        cl = build_checklist(ChecklistPeriod.PER_RELEASE, "v1.0.0")
        assert cl.period == ChecklistPeriod.PER_RELEASE
        assert cl.reference == "v1.0.0"
        assert len(cl.items) == 5
        ids = [item.check_id for item in cl.items]
        assert ids == ["CI-01", "CI-02", "CI-03", "CI-04", "CI-05"]

    def test_build_monthly_checklist(self):
        cl = build_checklist(ChecklistPeriod.MONTHLY, "2026-01")
        assert len(cl.items) == 5
        ids = [item.check_id for item in cl.items]
        assert ids == ["CI-06", "CI-07", "CI-08", "CI-09", "CI-10"]

    def test_build_quarterly_checklist(self):
        cl = build_checklist(ChecklistPeriod.QUARTERLY, "2026-Q1")
        assert len(cl.items) == 5
        ids = [item.check_id for item in cl.items]
        assert ids == ["CI-11", "CI-12", "CI-13", "CI-14", "CI-15"]

    def test_evaluate_incomplete(self):
        cl = build_checklist(ChecklistPeriod.PER_RELEASE)
        evaluator = ChecklistEvaluator()
        complete, incomplete = evaluator.evaluate(cl)
        assert complete is False
        assert len(incomplete) == 5

    def test_evaluate_complete(self):
        cl = build_checklist(ChecklistPeriod.PER_RELEASE)
        evaluator = ChecklistEvaluator()
        for item in cl.items:
            item.completed = True
        complete, incomplete = evaluator.evaluate(cl)
        assert complete is True
        assert incomplete == []

    def test_complete_item(self):
        cl = build_checklist(ChecklistPeriod.PER_RELEASE)
        evaluator = ChecklistEvaluator()
        item = evaluator.complete_item(cl, "CI-01", "Done in retro")
        assert item is not None
        assert item.completed is True
        assert item.notes == "Done in retro"

    def test_complete_item_not_found(self):
        cl = build_checklist(ChecklistPeriod.PER_RELEASE)
        evaluator = ChecklistEvaluator()
        item = evaluator.complete_item(cl, "CI-99")
        assert item is None

    def test_partial_completion(self):
        cl = build_checklist(ChecklistPeriod.MONTHLY)
        evaluator = ChecklistEvaluator()
        evaluator.complete_item(cl, "CI-06")
        evaluator.complete_item(cl, "CI-08")
        complete, incomplete = evaluator.evaluate(cl)
        assert complete is False
        assert len(incomplete) == 3


# ===========================================================================
# Metrics
# ===========================================================================


class TestMetrics:
    """Test improvement metrics computation and tracking."""

    def test_default_metrics(self):
        metrics = default_metrics()
        assert len(metrics) == 5
        ids = [m.metric_id for m in metrics]
        assert ids == ["IM-01", "IM-02", "IM-03", "IM-04", "IM-05"]

    def test_compute_trend_improving(self):
        values = [10.0, 12.0, 15.0, 18.0]
        assert compute_trend(values) == MetricTrend.IMPROVING

    def test_compute_trend_declining(self):
        values = [18.0, 15.0, 12.0, 10.0]
        assert compute_trend(values) == MetricTrend.DECLINING

    def test_compute_trend_stable(self):
        values = [10.0, 10.1, 9.9, 10.0]
        assert compute_trend(values) == MetricTrend.STABLE

    def test_compute_trend_insufficient_data(self):
        assert compute_trend([]) == MetricTrend.STABLE
        assert compute_trend([5.0]) == MetricTrend.STABLE

    def test_tracker_save_and_latest(self):
        tracker = MetricsTracker()
        snap = MetricsSnapshot(period="2026-Q1")
        tracker.save_snapshot(snap)
        assert tracker.latest() is snap

    def test_tracker_empty_latest(self):
        tracker = MetricsTracker()
        assert tracker.latest() is None

    def test_tracker_list_snapshots(self):
        tracker = MetricsTracker()
        for i in range(5):
            tracker.save_snapshot(MetricsSnapshot(period=f"P{i}"))
        result = tracker.list_snapshots(3)
        assert len(result) == 3
        # Newest first
        assert result[0].period == "P4"
        assert result[2].period == "P2"

    def test_tracker_get_trend(self):
        tracker = MetricsTracker()
        for val in [10.0, 12.0, 15.0, 18.0]:
            tracker.save_snapshot(
                MetricsSnapshot(
                    metrics=[
                        ImprovementMetric(
                            metric_id="IM-01",
                            name="Cycle time",
                            current=val,
                        )
                    ]
                )
            )
        trend, values = tracker.get_trend("IM-01", periods=4)
        assert trend == MetricTrend.IMPROVING
        assert values == [10.0, 12.0, 15.0, 18.0]

    def test_tracker_get_trend_missing_metric(self):
        tracker = MetricsTracker()
        tracker.save_snapshot(MetricsSnapshot())
        trend, values = tracker.get_trend("IM-99")
        assert trend == MetricTrend.STABLE
        assert values == []


# ===========================================================================
# Service
# ===========================================================================


class TestService:
    """Test ImprovementService orchestration logic."""

    # ----- Research Intake -------------------------------------------------

    def test_submit_and_get_intake(self, service: ImprovementService):
        intake = ResearchIntake(
            content=IntakeContent(title="Test"),
            submitted_by="tester",
        )
        result = service.submit_intake(intake)
        assert result.disposition.status == IntakeStatus.SUBMITTED
        fetched = service.get_intake(result.intake_id)
        assert fetched is not None
        assert fetched.content.title == "Test"

    def test_list_intakes_filter_status(self, service: ImprovementService):
        service.submit_intake(ResearchIntake(content=IntakeContent(title="A")))
        service.submit_intake(ResearchIntake(content=IntakeContent(title="B")))
        result = service.list_intakes(status=IntakeStatus.SUBMITTED)
        assert len(result) == 2
        result = service.list_intakes(status=IntakeStatus.ACCEPTED)
        assert len(result) == 0

    def test_list_intakes_filter_type(self, service: ImprovementService):
        i1 = ResearchIntake(
            content=IntakeContent(title="A"),
            classification=IntakeClassification(research_type=ResearchType.EXTERNAL),
        )
        i2 = ResearchIntake(
            content=IntakeContent(title="B"),
            classification=IntakeClassification(research_type=ResearchType.INTERNAL),
        )
        service.submit_intake(i1)
        service.submit_intake(i2)
        result = service.list_intakes(research_type="external")
        assert len(result) == 1
        assert result[0].content.title == "A"

    def test_intake_lifecycle(self, service: ImprovementService):
        intake = service.submit_intake(
            ResearchIntake(content=IntakeContent(title="Lifecycle Test"))
        )
        iid = intake.intake_id

        # SUBMITTED -> TRIAGED
        result = service.transition_intake(iid, IntakeStatus.TRIAGED)
        assert result.disposition.status == IntakeStatus.TRIAGED

        # TRIAGED -> ANALYZING
        result = service.transition_intake(iid, IntakeStatus.ANALYZING)
        assert result.disposition.status == IntakeStatus.ANALYZING

        # ANALYZING -> ACCEPTED
        result = service.transition_intake(
            iid,
            IntakeStatus.ACCEPTED,
            decision_by="lead",
            rationale="High impact",
            action_items=["TASK-1"],
        )
        assert result.disposition.status == IntakeStatus.ACCEPTED
        assert result.disposition.decision_by == "lead"
        assert result.disposition.decision_date is not None

        # ACCEPTED -> TRACKED
        result = service.transition_intake(iid, IntakeStatus.TRACKED)
        assert result.disposition.status == IntakeStatus.TRACKED

    def test_intake_invalid_transition(self, service: ImprovementService):
        intake = service.submit_intake(ResearchIntake(content=IntakeContent(title="Invalid")))
        with pytest.raises(ValueError, match="Cannot transition"):
            service.transition_intake(intake.intake_id, IntakeStatus.ACCEPTED)

    def test_intake_not_found(self, service: ImprovementService):
        with pytest.raises(ValueError, match="not found"):
            service.transition_intake("nonexistent", IntakeStatus.TRIAGED)

    def test_intake_deferred_can_retriage(self, service: ImprovementService):
        intake = service.submit_intake(ResearchIntake(content=IntakeContent(title="Defer")))
        iid = intake.intake_id
        service.transition_intake(iid, IntakeStatus.TRIAGED)
        service.transition_intake(iid, IntakeStatus.ANALYZING)
        service.transition_intake(iid, IntakeStatus.DEFERRED)
        # Can go back to TRIAGED
        result = service.transition_intake(iid, IntakeStatus.TRIAGED)
        assert result.disposition.status == IntakeStatus.TRIAGED

    # ----- Lessons Learned -------------------------------------------------

    def test_record_and_get_lesson(self, service: ImprovementService):
        lesson = LessonLearned(
            phase="14",
            event_type=LessonEventType.FAILURE,
            what_happened="Build broke",
            root_cause="Missing dep",
        )
        result = service.record_lesson(lesson)
        assert result.lesson_id.startswith("LL-")
        fetched = service.get_lesson(result.lesson_id)
        assert fetched is not None
        assert fetched.what_happened == "Build broke"

    def test_list_lessons_filter(self, service: ImprovementService):
        service.record_lesson(
            LessonLearned(
                phase="14",
                event_type=LessonEventType.FAILURE,
            )
        )
        service.record_lesson(
            LessonLearned(
                phase="15",
                event_type=LessonEventType.SUCCESS,
            )
        )
        assert len(service.list_lessons(phase="14")) == 1
        assert len(service.list_lessons(event_type="success")) == 1

    def test_complete_lesson_action(self, service: ImprovementService):
        lesson = service.record_lesson(
            LessonLearned(
                actions=[
                    LessonAction(description="Fix CI"),
                    LessonAction(description="Update docs"),
                ]
            )
        )
        result = service.complete_lesson_action(lesson.lesson_id, 0)
        assert result.actions[0].status == LessonActionStatus.COMPLETED
        assert result.actions[1].status == LessonActionStatus.PENDING

    def test_complete_lesson_action_out_of_range(self, service: ImprovementService):
        lesson = service.record_lesson(LessonLearned())
        with pytest.raises(ValueError, match="out of range"):
            service.complete_lesson_action(lesson.lesson_id, 0)

    def test_verify_lesson(self, service: ImprovementService):
        lesson = service.record_lesson(LessonLearned())
        result = service.verify_lesson(lesson.lesson_id, evidence="PR #42")
        assert result.implemented is True
        assert result.verified_at is not None
        assert result.evidence == "PR #42"

    # ----- Checklists ------------------------------------------------------

    def test_create_checklist(self, service: ImprovementService):
        cl = service.create_checklist(ChecklistPeriod.PER_RELEASE, "v1.0.0")
        assert len(cl.items) == 5
        fetched = service.get_checklist(cl.checklist_id)
        assert fetched is not None

    def test_list_checklists_filter(self, service: ImprovementService):
        service.create_checklist(ChecklistPeriod.PER_RELEASE)
        service.create_checklist(ChecklistPeriod.MONTHLY)
        assert len(service.list_checklists()) == 2
        assert len(service.list_checklists(ChecklistPeriod.MONTHLY)) == 1

    def test_complete_checklist_item_via_service(self, service: ImprovementService):
        cl = service.create_checklist(ChecklistPeriod.PER_RELEASE)
        result = service.complete_checklist_item(cl.checklist_id, "CI-01", "Done")
        assert result.items[0].completed is True

    def test_evaluate_checklist_via_service(self, service: ImprovementService):
        cl = service.create_checklist(ChecklistPeriod.PER_RELEASE)
        ok, incomplete = service.evaluate_checklist(cl.checklist_id)
        assert ok is False
        assert len(incomplete) == 5

    # ----- Metrics ---------------------------------------------------------

    def test_default_snapshot(self, service: ImprovementService):
        snap = service.create_default_snapshot("2026-Q1")
        assert len(snap.metrics) == 5
        assert service.latest_metrics() is snap

    def test_save_and_list_snapshots(self, service: ImprovementService):
        for i in range(3):
            service.save_metrics_snapshot(MetricsSnapshot(period=f"P{i}"))
        result = service.list_metrics_snapshots(2)
        assert len(result) == 2

    def test_metric_trend(self, service: ImprovementService):
        for val in [10.0, 12.0, 15.0, 18.0]:
            service.save_metrics_snapshot(
                MetricsSnapshot(
                    metrics=[
                        ImprovementMetric(
                            metric_id="IM-01",
                            name="Cycle time",
                            current=val,
                        )
                    ]
                )
            )
        trend, values = service.get_metric_trend("IM-01")
        assert trend == "improving"
        assert len(values) == 4

    # ----- Roadmap Refresh -------------------------------------------------

    def test_record_and_get_refresh(self, service: ImprovementService):
        refresh = RoadmapRefresh(
            scope=RefreshScope.MAJOR,
            participants=["lead", "architect"],
            activities=["Full review"],
        )
        result = service.record_refresh(refresh)
        assert result.refresh_id.startswith("RMR-")
        fetched = service.get_refresh(result.refresh_id)
        assert fetched is not None

    def test_list_refreshes_filter(self, service: ImprovementService):
        service.record_refresh(RoadmapRefresh(scope=RefreshScope.MICRO))
        service.record_refresh(RoadmapRefresh(scope=RefreshScope.MAJOR))
        assert len(service.list_refreshes()) == 2
        assert len(service.list_refreshes(scope="major")) == 1

    def test_complete_refresh(self, service: ImprovementService):
        refresh = service.record_refresh(RoadmapRefresh())
        result = service.complete_refresh(
            refresh.refresh_id,
            outcome="Priorities rebalanced",
            changes=["Phase 20 moved up"],
        )
        assert result.completed_at is not None
        assert result.outcome == "Priorities rebalanced"
        assert len(result.changes_made) == 1

    def test_complete_refresh_not_found(self, service: ImprovementService):
        with pytest.raises(ValueError, match="not found"):
            service.complete_refresh("nonexistent")


# ===========================================================================
# API Routes
# ===========================================================================


@pytest.mark.usefixtures("_reset_routes")
class TestImprovementAPI:
    """Test REST endpoints for improvements."""

    # ----- Intake routes ---------------------------------------------------

    def test_submit_intake(self, client: TestClient):
        resp = client.post(
            "/v1/improvements/intakes",
            json={"title": "API Test", "submitted_by": "tester"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["intake_id"].startswith("RI-")
        assert data["content"]["title"] == "API Test"
        assert data["disposition"]["status"] == "submitted"

    def test_submit_intake_rejects_cross_tenant_override_for_authenticated_user(self):
        tenant_client = _tenant_client("tenant-a")
        resp = tenant_client.post(
            "/v1/improvements/intakes",
            json={"title": "Cross tenant", "tenant_id": "tenant-b"},
        )
        assert resp.status_code == 403
        assert "Tenant mismatch" in resp.json()["detail"]

    def test_submit_intake_rejects_authenticated_user_without_tenant_context(self):
        tenantless_client = _tenant_client("")
        resp = tenantless_client.post(
            "/v1/improvements/intakes",
            json={"title": "Tenantless auth"},
        )
        assert resp.status_code == 403
        assert "Tenant context required" in resp.json()["detail"]

    def test_list_intakes(self, client: TestClient):
        client.post(
            "/v1/improvements/intakes",
            json={"title": "A"},
        )
        client.post(
            "/v1/improvements/intakes",
            json={"title": "B"},
        )
        resp = client.get("/v1/improvements/intakes")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_list_intakes_rejects_cross_tenant_filter_for_authenticated_user(self):
        tenant_client = _tenant_client("tenant-a")
        tenant_client.post(
            "/v1/improvements/intakes",
            json={"title": "Tenant A intake", "tenant_id": "tenant-a"},
        )

        resp = tenant_client.get(
            "/v1/improvements/intakes",
            params={"tenant_id": "tenant-b"},
        )
        assert resp.status_code == 403
        assert "Tenant mismatch" in resp.json()["detail"]

    def test_submit_competitive_repo_intakes_batch(self, client: TestClient):
        resp = client.post(
            "/v1/improvements/intakes/competitive/repos",
            json={
                "records": [
                    {
                        "rank": 1,
                        "full_name": "org/alpha",
                        "url": "https://github.com/org/alpha",
                        "stars": 12345,
                        "source_query": "agent framework",
                    },
                    {
                        "rank": 2,
                        "full_name": "org/beta",
                        "url": "https://github.com/org/beta",
                        "stars": 9876,
                        "source_query": "agent framework",
                    },
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["created_intakes"]) == 2
        assert data["created_intakes"][0]["classification"]["research_type"] == "competitive"
        assert data["created_intakes"][1]["content"]["source"] == "https://github.com/org/beta"

    def test_score_and_prioritize_feature_candidates(self, client: TestClient):
        resp = client.post(
            "/v1/improvements/feature-candidates/score",
            json={
                "top_n": 2,
                "candidates": [
                    {
                        "feature_name": "Feature A",
                        "impact_score": 8,
                        "feasibility_score": 8,
                        "risk_score": 3,
                    },
                    {
                        "feature_name": "Feature B",
                        "impact_score": 6,
                        "feasibility_score": 7,
                        "risk_score": 8,
                    },
                    {
                        "feature_name": "Feature C",
                        "impact_score": 9,
                        "feasibility_score": 9,
                        "risk_score": 2,
                    },
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["scored"]) == 3
        assert len(data["prioritized"]) == 2
        assert data["prioritized"][0]["feature_name"] == "Feature C"

    def test_submit_competitive_repo_intakes_invalid_rank(self, client: TestClient):
        resp = client.post(
            "/v1/improvements/intakes/competitive/repos",
            json={
                "records": [
                    {
                        "rank": 0,
                        "full_name": "org/alpha",
                        "url": "https://github.com/org/alpha",
                        "stars": 12345,
                    }
                ]
            },
        )
        assert resp.status_code == 422

    def test_score_feature_candidates_invalid_top_n(self, client: TestClient):
        resp = client.post(
            "/v1/improvements/feature-candidates/score",
            json={"top_n": 0, "candidates": []},
        )
        assert resp.status_code == 422

    def test_list_intakes_filter_status(self, client: TestClient):
        client.post(
            "/v1/improvements/intakes",
            json={"title": "A"},
        )
        resp = client.get("/v1/improvements/intakes", params={"status": "submitted"})
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        resp = client.get("/v1/improvements/intakes", params={"status": "accepted"})
        assert len(resp.json()) == 0

    def test_get_intake(self, client: TestClient):
        resp = client.post(
            "/v1/improvements/intakes",
            json={"title": "Get Test"},
        )
        intake_id = resp.json()["intake_id"]
        resp = client.get(f"/v1/improvements/intakes/{intake_id}")
        assert resp.status_code == 200
        assert resp.json()["content"]["title"] == "Get Test"

    def test_get_intake_is_tenant_scoped(self):
        tenant_a = _tenant_client("tenant-a")
        tenant_b = _tenant_client("tenant-b")

        created = tenant_a.post(
            "/v1/improvements/intakes",
            json={"title": "Tenant A only", "tenant_id": "tenant-a"},
        )
        intake_id = created.json()["intake_id"]

        allowed = tenant_a.get(f"/v1/improvements/intakes/{intake_id}")
        denied = tenant_b.get(f"/v1/improvements/intakes/{intake_id}")

        assert allowed.status_code == 200
        assert denied.status_code == 404

    def test_get_intake_rejects_authenticated_user_without_tenant_context(
        self, client: TestClient
    ):
        created = client.post(
            "/v1/improvements/intakes",
            json={"title": "Tenant-protected intake"},
        )
        intake_id = created.json()["intake_id"]
        tenantless_client = _tenant_client("")

        denied = tenantless_client.get(f"/v1/improvements/intakes/{intake_id}")
        assert denied.status_code == 403
        assert "Tenant context required" in denied.json()["detail"]

    def test_get_intake_not_found(self, client: TestClient):
        resp = client.get("/v1/improvements/intakes/nonexistent")
        assert resp.status_code == 404

    def test_transition_intake(self, client: TestClient):
        resp = client.post(
            "/v1/improvements/intakes",
            json={"title": "Transition"},
        )
        intake_id = resp.json()["intake_id"]
        resp = client.post(
            f"/v1/improvements/intakes/{intake_id}/transition",
            json={"new_status": "triaged"},
        )
        assert resp.status_code == 200
        assert resp.json()["disposition"]["status"] == "triaged"

    def test_transition_intake_invalid(self, client: TestClient):
        resp = client.post(
            "/v1/improvements/intakes",
            json={"title": "Invalid"},
        )
        intake_id = resp.json()["intake_id"]
        resp = client.post(
            f"/v1/improvements/intakes/{intake_id}/transition",
            json={"new_status": "accepted"},
        )
        assert resp.status_code == 400

    def test_transition_intake_is_tenant_scoped(self):
        tenant_a = _tenant_client("tenant-a")
        tenant_b = _tenant_client("tenant-b")

        created = tenant_a.post(
            "/v1/improvements/intakes",
            json={"title": "Tenant transition", "tenant_id": "tenant-a"},
        )
        intake_id = created.json()["intake_id"]

        denied = tenant_b.post(
            f"/v1/improvements/intakes/{intake_id}/transition",
            json={"new_status": "triaged"},
        )
        assert denied.status_code == 404

    # ----- Lesson routes ---------------------------------------------------

    def test_record_lesson(self, client: TestClient):
        resp = client.post(
            "/v1/improvements/lessons",
            json={
                "phase": "14",
                "event_type": "failure",
                "what_happened": "Build broke",
                "actions": [{"description": "Fix CI"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["lesson_id"].startswith("LL-")
        assert data["phase"] == "14"
        assert len(data["actions"]) == 1

    def test_list_lessons(self, client: TestClient):
        client.post(
            "/v1/improvements/lessons",
            json={"phase": "14", "event_type": "failure"},
        )
        resp = client.get("/v1/improvements/lessons")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_get_lesson(self, client: TestClient):
        resp = client.post(
            "/v1/improvements/lessons",
            json={"what_happened": "Test event"},
        )
        lesson_id = resp.json()["lesson_id"]
        resp = client.get(f"/v1/improvements/lessons/{lesson_id}")
        assert resp.status_code == 200
        assert resp.json()["what_happened"] == "Test event"

    def test_verify_lesson(self, client: TestClient):
        resp = client.post(
            "/v1/improvements/lessons",
            json={"what_happened": "Verify test"},
        )
        lesson_id = resp.json()["lesson_id"]
        resp = client.post(
            f"/v1/improvements/lessons/{lesson_id}/verify",
            json={"evidence": "PR #99"},
        )
        assert resp.status_code == 200
        assert resp.json()["implemented"] is True

    # ----- Checklist routes ------------------------------------------------

    def test_create_checklist(self, client: TestClient):
        resp = client.post(
            "/v1/improvements/checklists",
            json={"period": "per_release", "reference": "v1.0.0"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 5
        assert data["items"][0]["check_id"] == "CI-01"

    def test_list_checklists(self, client: TestClient):
        client.post(
            "/v1/improvements/checklists",
            json={"period": "per_release"},
        )
        client.post(
            "/v1/improvements/checklists",
            json={"period": "monthly"},
        )
        resp = client.get("/v1/improvements/checklists")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_complete_checklist_item(self, client: TestClient):
        resp = client.post(
            "/v1/improvements/checklists",
            json={"period": "per_release"},
        )
        cl_id = resp.json()["checklist_id"]
        resp = client.post(
            f"/v1/improvements/checklists/{cl_id}/complete",
            json={"check_id": "CI-01", "notes": "Done"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        ci01 = [i for i in items if i["check_id"] == "CI-01"][0]
        assert ci01["completed"] is True
        assert ci01["notes"] == "Done"

    def test_evaluate_checklist(self, client: TestClient):
        resp = client.post(
            "/v1/improvements/checklists",
            json={"period": "per_release"},
        )
        cl_id = resp.json()["checklist_id"]
        resp = client.get(f"/v1/improvements/checklists/{cl_id}/evaluate")
        assert resp.status_code == 200
        assert resp.json()["complete"] is False
        assert len(resp.json()["incomplete"]) == 5

    # ----- Metrics routes --------------------------------------------------

    def test_get_latest_metrics_empty(self, client: TestClient):
        resp = client.get("/v1/improvements/metrics")
        assert resp.status_code == 200
        assert resp.json()["snapshot"] is None

    def test_create_default_snapshot(self, client: TestClient):
        resp = client.post(
            "/v1/improvements/metrics/default-snapshot",
            params={"period": "2026-Q1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["metrics"]) == 5
        assert data["period"] == "2026-Q1"

    def test_save_snapshot(self, client: TestClient):
        resp = client.post(
            "/v1/improvements/metrics/snapshot",
            json={
                "period": "2026-Q1",
                "metrics": [
                    {
                        "metric_id": "IM-01",
                        "name": "Cycle time",
                        "current": 24.5,
                    }
                ],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["metrics"][0]["current"] == 24.5

    def test_metrics_history(self, client: TestClient):
        for i in range(3):
            client.post(
                "/v1/improvements/metrics/snapshot",
                json={"period": f"P{i}"},
            )
        resp = client.get("/v1/improvements/metrics/history", params={"limit": 2})
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_metric_trend(self, client: TestClient):
        for val in [10.0, 12.0, 15.0, 18.0]:
            client.post(
                "/v1/improvements/metrics/snapshot",
                json={
                    "metrics": [
                        {
                            "metric_id": "IM-01",
                            "name": "Cycle time",
                            "current": val,
                        }
                    ]
                },
            )
        resp = client.get("/v1/improvements/metrics/trend/IM-01")
        assert resp.status_code == 200
        assert resp.json()["trend"] == "improving"

    # ----- Refresh routes --------------------------------------------------

    def test_record_refresh(self, client: TestClient):
        resp = client.post(
            "/v1/improvements/refreshes",
            json={
                "scope": "major",
                "participants": ["lead"],
                "activities": ["Full review"],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["scope"] == "major"

    def test_list_refreshes(self, client: TestClient):
        client.post(
            "/v1/improvements/refreshes",
            json={"scope": "micro"},
        )
        resp = client.get("/v1/improvements/refreshes")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_complete_refresh(self, client: TestClient):
        resp = client.post(
            "/v1/improvements/refreshes",
            json={"scope": "minor"},
        )
        rid = resp.json()["refresh_id"]
        resp = client.post(
            f"/v1/improvements/refreshes/{rid}/complete",
            json={"outcome": "Priorities updated", "changes": ["Phase 20"]},
        )
        assert resp.status_code == 200
        assert resp.json()["outcome"] == "Priorities updated"
        assert resp.json()["completed_at"] is not None
