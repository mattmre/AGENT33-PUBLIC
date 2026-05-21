"""P72 Impact Dashboard — persistence, WoW, failure modes, ROI, pack impact."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from agent33.api.routes import outcomes as outcomes_mod
from agent33.main import app
from agent33.outcomes.models import (
    FailureModeStat,
    OutcomeEvent,
    OutcomeEventCreate,
    OutcomeMetricType,
    PackImpactEntry,
    PackImpactResponse,
    ROIRequest,
    ROIResponse,
    WeekOverWeekStat,
)
from agent33.outcomes.persistence import OutcomePersistence
from agent33.outcomes.service import OutcomesService
from agent33.security.auth import create_access_token

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path / "test_outcomes.db"


@pytest.fixture
def persistence(tmp_db: Path) -> OutcomePersistence:
    return OutcomePersistence(tmp_db)


@pytest.fixture
def service(persistence: OutcomePersistence) -> OutcomesService:
    return OutcomesService(persistence=persistence)


@pytest.fixture
def service_no_persist() -> OutcomesService:
    return OutcomesService()


def _make_event(
    *,
    tenant_id: str = "t1",
    domain: str = "qa",
    event_type: str = "invoke",
    metric_type: OutcomeMetricType = OutcomeMetricType.SUCCESS_RATE,
    value: float = 1.0,
    occurred_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> OutcomeEventCreate:
    return OutcomeEventCreate(
        domain=domain,
        event_type=event_type,
        metric_type=metric_type,
        value=value,
        occurred_at=occurred_at,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# API test infrastructure
# ---------------------------------------------------------------------------


def _client(scopes: list[str], *, tenant_id: str = "tenant-a") -> TestClient:
    token = create_access_token("impact-user", scopes=scopes, tenant_id=tenant_id)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture(autouse=True)
def reset_outcomes_service() -> Any:
    """Ensure each test starts with a clean, persistence-free _service.

    Replaces the module-level ``_service`` with a fresh ``OutcomesService()``
    (no persistence) to avoid inheriting a closed SQLite connection from a
    prior lifespan teardown (P72 fix).
    """
    saved_service = outcomes_mod._service
    outcomes_mod._service = OutcomesService()
    had_attr = hasattr(app.state, "outcomes_service")
    saved_state = getattr(app.state, "outcomes_service", None)
    if had_attr:
        delattr(app.state, "outcomes_service")
    yield
    outcomes_mod._service = saved_service
    if had_attr:
        app.state.outcomes_service = saved_state
    elif hasattr(app.state, "outcomes_service"):
        delattr(app.state, "outcomes_service")


@pytest.fixture
def writer_client() -> TestClient:
    return _client(["outcomes:read", "outcomes:write"])


@pytest.fixture
def reader_client() -> TestClient:
    return _client(["outcomes:read"])


@pytest.fixture
def no_scope_client() -> TestClient:
    return _client([])


@pytest.fixture
def anonymous_client() -> TestClient:
    return TestClient(app)


# ===========================================================================
# 1. OutcomePersistence tests
# ===========================================================================


class TestOutcomePersistence:
    """SQLite persistence layer tests."""

    def test_save_and_load_round_trip(self, persistence: OutcomePersistence) -> None:
        """Events saved can be loaded back with all fields intact."""
        now = datetime.now(UTC)
        event = OutcomeEvent(
            id="test-001",
            tenant_id="t1",
            domain="qa",
            event_type="invoke",
            metric_type=OutcomeMetricType.SUCCESS_RATE,
            value=0.95,
            occurred_at=now,
            metadata={"model": "llama3.2", "session_id": "sess-1"},
        )
        persistence.save_event(event)
        loaded = persistence.load_events(tenant_id="t1")
        assert len(loaded) == 1
        assert loaded[0].id == "test-001"
        assert loaded[0].tenant_id == "t1"
        assert loaded[0].domain == "qa"
        assert loaded[0].metric_type == OutcomeMetricType.SUCCESS_RATE
        assert loaded[0].value == 0.95
        assert loaded[0].metadata["model"] == "llama3.2"
        assert loaded[0].metadata["session_id"] == "sess-1"

    def test_load_filters_by_tenant(self, persistence: OutcomePersistence) -> None:
        """Events from different tenants are not mixed."""
        for tid in ("t1", "t2"):
            event = OutcomeEvent(
                tenant_id=tid,
                domain="qa",
                event_type="invoke",
                metric_type=OutcomeMetricType.SUCCESS_RATE,
                value=1.0,
            )
            persistence.save_event(event)
        assert len(persistence.load_events(tenant_id="t1")) == 1
        assert len(persistence.load_events(tenant_id="t2")) == 1
        assert len(persistence.load_events(tenant_id="t3")) == 0

    def test_load_filters_by_since(self, persistence: OutcomePersistence) -> None:
        """The since parameter filters out older events."""
        old_time = datetime(2025, 1, 1, tzinfo=UTC)
        new_time = datetime(2026, 3, 1, tzinfo=UTC)
        for ts in (old_time, new_time):
            event = OutcomeEvent(
                tenant_id="t1",
                domain="qa",
                event_type="invoke",
                metric_type=OutcomeMetricType.SUCCESS_RATE,
                value=1.0,
                occurred_at=ts,
            )
            persistence.save_event(event)
        cutoff = datetime(2026, 1, 1, tzinfo=UTC)
        loaded = persistence.load_events(tenant_id="t1", since=cutoff)
        assert len(loaded) == 1
        assert loaded[0].occurred_at.year == 2026
        assert loaded[0].occurred_at.month == 3

    def test_load_respects_limit(self, persistence: OutcomePersistence) -> None:
        """The limit parameter caps how many events are returned."""
        for i in range(10):
            event = OutcomeEvent(
                tenant_id="t1",
                domain="qa",
                event_type="invoke",
                metric_type=OutcomeMetricType.SUCCESS_RATE,
                value=float(i),
                occurred_at=datetime.now(UTC) + timedelta(seconds=i),
            )
            persistence.save_event(event)
        loaded = persistence.load_events(tenant_id="t1", limit=3)
        assert len(loaded) == 3

    def test_upsert_on_duplicate_id(self, persistence: OutcomePersistence) -> None:
        """Saving an event with the same ID replaces the old one."""
        event = OutcomeEvent(
            id="dup-001",
            tenant_id="t1",
            domain="qa",
            event_type="invoke",
            metric_type=OutcomeMetricType.SUCCESS_RATE,
            value=0.5,
        )
        persistence.save_event(event)
        event2 = OutcomeEvent(
            id="dup-001",
            tenant_id="t1",
            domain="qa",
            event_type="invoke",
            metric_type=OutcomeMetricType.SUCCESS_RATE,
            value=0.9,
        )
        persistence.save_event(event2)
        loaded = persistence.load_events(tenant_id="t1")
        assert len(loaded) == 1
        assert loaded[0].value == 0.9

    def test_close_is_safe_to_call_twice(self, persistence: OutcomePersistence) -> None:
        """Calling close multiple times does not raise."""
        persistence.close()
        persistence.close()  # should not raise

    def test_metadata_json_serialization(self, persistence: OutcomePersistence) -> None:
        """Complex metadata round-trips through JSON correctly."""
        event = OutcomeEvent(
            tenant_id="t1",
            domain="qa",
            event_type="invoke",
            metric_type=OutcomeMetricType.FAILURE_CLASS,
            value=1.0,
            metadata={"failure_class": "timeout", "nested": {"key": [1, 2, 3]}},
        )
        persistence.save_event(event)
        loaded = persistence.load_events(tenant_id="t1")
        assert loaded[0].metadata["failure_class"] == "timeout"
        assert loaded[0].metadata["nested"]["key"] == [1, 2, 3]

    def test_schema_creates_index(self, tmp_db: Path) -> None:
        """The persistence layer creates the expected index on the table."""
        OutcomePersistence(tmp_db)
        conn = sqlite3.connect(str(tmp_db))
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='outcome_events'"
        ).fetchall()
        index_names = {row[0] for row in indexes}
        assert "idx_tenant_occurred" in index_names
        conn.close()


# ===========================================================================
# 2. OutcomesService with persistence
# ===========================================================================


class TestServiceWithPersistence:
    """OutcomesService records events to SQLite when persistence is set."""

    def test_record_event_persists_to_sqlite(self, service: OutcomesService, tmp_db: Path) -> None:
        """Recording via service also writes to the SQLite file."""
        service.record_event(
            tenant_id="t1",
            event=_make_event(value=0.88),
        )
        # Open a raw connection to confirm data is in the DB
        conn = sqlite3.connect(str(tmp_db))
        rows = conn.execute("SELECT COUNT(*) FROM outcome_events").fetchone()
        assert rows[0] == 1
        conn.close()

    def test_record_event_without_persistence(self, service_no_persist: OutcomesService) -> None:
        """Service without persistence stores in memory only."""
        created = service_no_persist.record_event(
            tenant_id="t1",
            event=_make_event(value=0.77),
        )
        assert created.value == 0.77
        events = service_no_persist.list_events(tenant_id="t1")
        assert len(events) == 1

    def test_load_historical_merges_memory_and_db(self, persistence: OutcomePersistence) -> None:
        """load_historical returns union of in-memory and DB events, deduped."""
        # Insert directly into DB
        db_event = OutcomeEvent(
            id="db-only-001",
            tenant_id="t1",
            domain="qa",
            event_type="invoke",
            metric_type=OutcomeMetricType.SUCCESS_RATE,
            value=0.5,
            occurred_at=datetime.now(UTC) - timedelta(hours=2),
        )
        persistence.save_event(db_event)

        # Create service with persistence and add an in-memory event
        svc = OutcomesService(persistence=persistence)
        svc.record_event(
            tenant_id="t1",
            event=_make_event(value=0.9),
        )
        # load_historical should see both
        historical = svc.load_historical("t1")
        assert len(historical) == 2
        ids = {ev.id for ev in historical}
        assert "db-only-001" in ids

    def test_load_historical_deduplicates_by_id(self, persistence: OutcomePersistence) -> None:
        """In-memory events override DB rows with the same ID."""
        # Insert into DB
        event = OutcomeEvent(
            id="shared-001",
            tenant_id="t1",
            domain="qa",
            event_type="invoke",
            metric_type=OutcomeMetricType.SUCCESS_RATE,
            value=0.3,
        )
        persistence.save_event(event)

        svc = OutcomesService(persistence=persistence)
        # Manually put same ID in memory with different value
        mem_event = OutcomeEvent(
            id="shared-001",
            tenant_id="t1",
            domain="qa",
            event_type="invoke",
            metric_type=OutcomeMetricType.SUCCESS_RATE,
            value=0.99,
        )
        svc._events[mem_event.id] = mem_event

        historical = svc.load_historical("t1")
        assert len(historical) == 1
        assert historical[0].value == 0.99  # memory wins


# ===========================================================================
# 3. Week-over-week computation
# ===========================================================================


class TestWeekOverWeek:
    """Week-over-week trend computation."""

    def test_wow_with_two_weeks_of_data(self, service: OutcomesService) -> None:
        """Events split across current and previous weeks compute pct_change."""
        now = datetime.now(UTC)
        # Previous week: 3 events averaging 0.6
        for i in range(3):
            service.record_event(
                tenant_id="t1",
                event=_make_event(
                    value=0.6,
                    occurred_at=now - timedelta(days=10 - i),
                ),
            )
        # Current week: 3 events averaging 0.9
        for i in range(3):
            service.record_event(
                tenant_id="t1",
                event=_make_event(
                    value=0.9,
                    occurred_at=now - timedelta(hours=i + 1),
                ),
            )
        dashboard = service.get_dashboard(tenant_id="t1")
        wow = dashboard.week_over_week
        assert len(wow) == 4  # 4 numeric metric types
        sr = next(w for w in wow if w.metric_type == OutcomeMetricType.SUCCESS_RATE)
        assert sr.previous_week_avg == pytest.approx(0.6, abs=0.01)
        assert sr.current_week_avg == pytest.approx(0.9, abs=0.01)
        # (0.9 - 0.6) / 0.6 * 100 = 50.0%
        assert sr.pct_change == pytest.approx(50.0, abs=0.5)

    def test_wow_zero_previous_returns_zero_pct(self, service: OutcomesService) -> None:
        """When previous week has no data, pct_change is 0."""
        now = datetime.now(UTC)
        service.record_event(
            tenant_id="t1",
            event=_make_event(value=0.8, occurred_at=now - timedelta(hours=1)),
        )
        dashboard = service.get_dashboard(tenant_id="t1")
        sr = next(
            w for w in dashboard.week_over_week if w.metric_type == OutcomeMetricType.SUCCESS_RATE
        )
        assert sr.pct_change == 0.0

    def test_wow_no_data_returns_zeros(self, service: OutcomesService) -> None:
        """With no events at all, all WoW stats are zero."""
        dashboard = service.get_dashboard(tenant_id="t1")
        for stat in dashboard.week_over_week:
            assert stat.current_week_avg == 0.0
            assert stat.previous_week_avg == 0.0
            assert stat.pct_change == 0.0


# ===========================================================================
# 4. Top failure modes
# ===========================================================================


class TestFailureModes:
    """Failure mode aggregation from FAILURE_CLASS events."""

    def test_top_failure_modes_counted_correctly(self, service: OutcomesService) -> None:
        """Failure classes are counted and ordered by frequency."""
        for _ in range(5):
            service.record_event(
                tenant_id="t1",
                event=_make_event(
                    metric_type=OutcomeMetricType.FAILURE_CLASS,
                    value=1.0,
                    metadata={"failure_class": "timeout"},
                ),
            )
        for _ in range(3):
            service.record_event(
                tenant_id="t1",
                event=_make_event(
                    metric_type=OutcomeMetricType.FAILURE_CLASS,
                    value=1.0,
                    metadata={"failure_class": "rate_limit"},
                ),
            )
        dashboard = service.get_dashboard(tenant_id="t1")
        fm = dashboard.top_failure_modes
        assert len(fm) == 2
        assert fm[0].failure_class == "timeout"
        assert fm[0].count == 5
        assert fm[1].failure_class == "rate_limit"
        assert fm[1].count == 3

    def test_missing_failure_class_defaults_to_unknown(self, service: OutcomesService) -> None:
        """Events without failure_class metadata key are counted as 'unknown'."""
        service.record_event(
            tenant_id="t1",
            event=_make_event(
                metric_type=OutcomeMetricType.FAILURE_CLASS,
                value=1.0,
                metadata={},
            ),
        )
        dashboard = service.get_dashboard(tenant_id="t1")
        assert dashboard.top_failure_modes[0].failure_class == "unknown"

    def test_no_failure_events_returns_empty(self, service: OutcomesService) -> None:
        """When no FAILURE_CLASS events exist, top_failure_modes is empty."""
        service.record_event(
            tenant_id="t1",
            event=_make_event(metric_type=OutcomeMetricType.SUCCESS_RATE, value=1.0),
        )
        dashboard = service.get_dashboard(tenant_id="t1")
        assert dashboard.top_failure_modes == []


# ===========================================================================
# 5. ROI estimator
# ===========================================================================


class TestROI:
    """ROI computation logic."""

    def test_roi_basic_calculation(self, service: OutcomesService) -> None:
        """ROI correctly computes hours saved, value, and success rate."""
        now = datetime.now(UTC)
        # 10 success events (value=1.0)
        for i in range(10):
            service.record_event(
                tenant_id="t1",
                event=_make_event(
                    domain="qa",
                    value=1.0,
                    occurred_at=now - timedelta(days=i),
                ),
            )
        # 5 failure events (value=0.0)
        for i in range(5):
            service.record_event(
                tenant_id="t1",
                event=_make_event(
                    domain="qa",
                    value=0.0,
                    occurred_at=now - timedelta(days=i),
                ),
            )
        # 3 latency samples
        for i in range(3):
            service.record_event(
                tenant_id="t1",
                event=_make_event(
                    domain="qa",
                    metric_type=OutcomeMetricType.LATENCY_MS,
                    value=1000.0 + i * 100,
                    occurred_at=now - timedelta(days=i),
                ),
            )

        result = service.compute_roi(
            tenant_id="t1",
            domain="qa",
            hours_saved_per_success=0.5,
            cost_per_hour_usd=150.0,
            window_days=30,
        )
        assert result["total_invocations"] == 15
        assert result["success_count"] == 10
        assert result["failure_count"] == 5
        assert result["estimated_hours_saved"] == 5.0  # 10 * 0.5
        assert result["estimated_value_usd"] == 750.0  # 5.0 * 150.0
        assert result["success_rate"] == pytest.approx(0.6667, abs=0.01)
        # avg latency: (1000 + 1100 + 1200) / 3 = 1100
        assert result["avg_latency_ms"] == pytest.approx(1100.0, abs=0.1)

    def test_roi_empty_domain(self, service: OutcomesService) -> None:
        """ROI for a domain with no events returns zeros."""
        result = service.compute_roi(
            tenant_id="t1",
            domain="nonexistent",
            hours_saved_per_success=1.0,
            cost_per_hour_usd=100.0,
        )
        assert result["total_invocations"] == 0
        assert result["success_rate"] == 0.0
        assert result["avg_latency_ms"] == 0.0

    def test_roi_respects_window(self, service: OutcomesService) -> None:
        """Events outside the window_days are excluded from ROI."""
        now = datetime.now(UTC)
        # Old event (60 days ago)
        service.record_event(
            tenant_id="t1",
            event=_make_event(
                domain="qa",
                value=1.0,
                occurred_at=now - timedelta(days=60),
            ),
        )
        # Recent event (1 day ago)
        service.record_event(
            tenant_id="t1",
            event=_make_event(
                domain="qa",
                value=1.0,
                occurred_at=now - timedelta(days=1),
            ),
        )
        result = service.compute_roi(
            tenant_id="t1",
            domain="qa",
            hours_saved_per_success=1.0,
            cost_per_hour_usd=100.0,
            window_days=7,
        )
        assert result["total_invocations"] == 1


# ===========================================================================
# 6. Eviction
# ===========================================================================


class TestEviction:
    """In-memory event eviction at _MAX_EVENTS_PER_TENANT."""

    def test_eviction_caps_at_max(self, service_no_persist: OutcomesService) -> None:
        """After exceeding 10,000 events for one tenant, oldest are evicted."""
        from agent33.outcomes.service import _MAX_EVENTS_PER_TENANT

        for i in range(_MAX_EVENTS_PER_TENANT + 5):
            service_no_persist.record_event(
                tenant_id="t1",
                event=_make_event(
                    value=float(i),
                    occurred_at=datetime.now(UTC) + timedelta(seconds=i),
                ),
            )
        tenant_events = [ev for ev in service_no_persist._events.values() if ev.tenant_id == "t1"]
        assert len(tenant_events) <= _MAX_EVENTS_PER_TENANT

    def test_eviction_does_not_affect_other_tenant(
        self, service_no_persist: OutcomesService
    ) -> None:
        """Eviction for t1 does not remove t2 events."""
        from agent33.outcomes.service import _MAX_EVENTS_PER_TENANT

        service_no_persist.record_event(
            tenant_id="t2",
            event=_make_event(value=42.0),
        )
        for i in range(_MAX_EVENTS_PER_TENANT + 1):
            service_no_persist.record_event(
                tenant_id="t1",
                event=_make_event(value=float(i)),
            )
        t2_events = [ev for ev in service_no_persist._events.values() if ev.tenant_id == "t2"]
        assert len(t2_events) == 1


# ===========================================================================
# 7. API endpoint tests
# ===========================================================================


class TestDashboardAPI:
    """API contract tests for enhanced dashboard."""

    def test_dashboard_includes_wow_and_failures(self, writer_client: TestClient) -> None:
        """Dashboard response now includes week_over_week and top_failure_modes."""
        writer_client.post(
            "/v1/outcomes/events",
            json={
                "domain": "qa",
                "event_type": "invoke",
                "metric_type": "success_rate",
                "value": 0.9,
            },
        )
        resp = writer_client.get("/v1/outcomes/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert "week_over_week" in data
        assert "top_failure_modes" in data
        assert isinstance(data["week_over_week"], list)
        assert isinstance(data["top_failure_modes"], list)

    def test_dashboard_wow_has_correct_shape(self, writer_client: TestClient) -> None:
        """Each WoW entry has the required fields."""
        writer_client.post(
            "/v1/outcomes/events",
            json={
                "domain": "qa",
                "event_type": "invoke",
                "metric_type": "success_rate",
                "value": 0.9,
            },
        )
        resp = writer_client.get("/v1/outcomes/dashboard")
        wow = resp.json()["week_over_week"]
        assert len(wow) == 4
        for entry in wow:
            assert "metric_type" in entry
            assert "current_week_avg" in entry
            assert "previous_week_avg" in entry
            assert "pct_change" in entry


class TestROIAPI:
    """API tests for /v1/outcomes/roi endpoint."""

    def test_roi_requires_auth(self, anonymous_client: TestClient) -> None:
        """ROI endpoint requires authentication."""
        resp = anonymous_client.post(
            "/v1/outcomes/roi",
            json={
                "domain": "qa",
                "hours_saved_per_success": 0.5,
                "cost_per_hour_usd": 150.0,
                "window_days": 30,
            },
        )
        assert resp.status_code == 401

    def test_roi_requires_scope(self, no_scope_client: TestClient) -> None:
        """ROI endpoint requires outcomes:read scope."""
        resp = no_scope_client.post(
            "/v1/outcomes/roi",
            json={
                "domain": "qa",
                "hours_saved_per_success": 0.5,
                "cost_per_hour_usd": 150.0,
            },
        )
        assert resp.status_code == 403

    def test_roi_returns_correct_shape(self, reader_client: TestClient) -> None:
        """ROI response has the expected fields."""
        resp = reader_client.post(
            "/v1/outcomes/roi",
            json={
                "domain": "qa",
                "hours_saved_per_success": 0.5,
                "cost_per_hour_usd": 150.0,
                "window_days": 30,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        expected_keys = {
            "total_invocations",
            "success_count",
            "failure_count",
            "estimated_hours_saved",
            "estimated_value_usd",
            "success_rate",
            "avg_latency_ms",
        }
        assert expected_keys <= set(data.keys())

    def test_roi_validates_domain_required(self, reader_client: TestClient) -> None:
        """ROI endpoint validates that domain is non-empty."""
        resp = reader_client.post(
            "/v1/outcomes/roi",
            json={
                "domain": "",
                "hours_saved_per_success": 0.5,
                "cost_per_hour_usd": 150.0,
            },
        )
        assert resp.status_code == 422

    def test_roi_computes_with_recorded_events(self, writer_client: TestClient) -> None:
        """ROI reflects events that were recorded through the API."""
        # Record some success events
        for _ in range(4):
            writer_client.post(
                "/v1/outcomes/events",
                json={
                    "domain": "delivery",
                    "event_type": "deploy",
                    "metric_type": "success_rate",
                    "value": 1.0,
                },
            )
        for _ in range(2):
            writer_client.post(
                "/v1/outcomes/events",
                json={
                    "domain": "delivery",
                    "event_type": "deploy",
                    "metric_type": "success_rate",
                    "value": 0.0,
                },
            )
        resp = writer_client.post(
            "/v1/outcomes/roi",
            json={
                "domain": "delivery",
                "hours_saved_per_success": 1.0,
                "cost_per_hour_usd": 100.0,
                "window_days": 30,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_invocations"] == 6
        assert data["success_count"] == 4
        assert data["failure_count"] == 2
        assert data["estimated_hours_saved"] == 4.0
        assert data["estimated_value_usd"] == 400.0


class TestPackImpactAPI:
    """API tests for /v1/outcomes/pack-impact endpoint."""

    def test_pack_impact_requires_auth(self, anonymous_client: TestClient) -> None:
        """Pack impact endpoint requires authentication."""
        resp = anonymous_client.get("/v1/outcomes/pack-impact")
        assert resp.status_code == 401

    def test_pack_impact_requires_scope(self, no_scope_client: TestClient) -> None:
        """Pack impact endpoint requires outcomes:read scope."""
        resp = no_scope_client.get("/v1/outcomes/pack-impact")
        assert resp.status_code == 403

    def test_pack_impact_no_registry_returns_503(self, reader_client: TestClient) -> None:
        """Without a pack registry, pack impact returns 503 Service Unavailable."""
        resp = reader_client.get("/v1/outcomes/pack-impact")
        assert resp.status_code == 503
        assert resp.json()["detail"] == "Pack registry not initialized"

    def test_pack_impact_with_mock_registry(self, writer_client: TestClient) -> None:
        """Pack impact correctly cross-references session packs and outcomes."""
        # Record events with session_id metadata
        writer_client.post(
            "/v1/outcomes/events",
            json={
                "domain": "qa",
                "event_type": "invoke",
                "metric_type": "success_rate",
                "value": 1.0,
                "metadata": {"session_id": "sess-1"},
            },
        )
        writer_client.post(
            "/v1/outcomes/events",
            json={
                "domain": "qa",
                "event_type": "invoke",
                "metric_type": "success_rate",
                "value": 0.0,
                "metadata": {"session_id": "sess-2"},
            },
        )

        # Mock pack registry with session mappings
        mock_registry = MagicMock()
        mock_registry._session_enabled = {
            "sess-1": {"web-research-pack"},
        }

        app.state.pack_registry = mock_registry
        try:
            resp = writer_client.get("/v1/outcomes/pack-impact")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["packs"]) == 1
            pack = data["packs"][0]
            assert pack["pack_name"] == "web-research-pack"
            assert pack["sessions_applied"] == 1
            # sess-1 (with pack) had 1 success out of 1 = 1.0
            assert pack["success_rate_with_pack"] == 1.0
            # sess-2 (without pack) had 0 successes out of 1 = 0.0
            assert pack["success_rate_without_pack"] == 0.0
            assert pack["delta"] == 1.0
        finally:
            if hasattr(app.state, "pack_registry"):
                delattr(app.state, "pack_registry")


# ===========================================================================
# 8. Model validation tests
# ===========================================================================


class TestModels:
    """Pydantic model validation for new P72 models."""

    def test_roi_request_validates_domain(self) -> None:
        """ROIRequest rejects empty domain."""
        with pytest.raises(ValueError):
            ROIRequest(domain="", hours_saved_per_success=0.5, cost_per_hour_usd=150)

    def test_roi_request_validates_negative_hours(self) -> None:
        """ROIRequest rejects negative hours_saved_per_success."""
        with pytest.raises(ValueError):
            ROIRequest(domain="qa", hours_saved_per_success=-1, cost_per_hour_usd=150)

    def test_roi_response_model_dump(self) -> None:
        """ROIResponse can be serialized to dict."""
        roi = ROIResponse(
            total_invocations=100,
            success_count=80,
            failure_count=20,
            estimated_hours_saved=40.0,
            estimated_value_usd=6000.0,
            success_rate=0.8,
            avg_latency_ms=500.0,
        )
        data = roi.model_dump()
        assert data["total_invocations"] == 100
        assert data["estimated_value_usd"] == 6000.0

    def test_pack_impact_response_model(self) -> None:
        """PackImpactResponse serializes correctly."""
        resp = PackImpactResponse(
            packs=[
                PackImpactEntry(
                    pack_name="test-pack",
                    sessions_applied=5,
                    success_rate_with_pack=0.9,
                    success_rate_without_pack=0.7,
                    delta=0.2,
                )
            ]
        )
        data = resp.model_dump()
        assert len(data["packs"]) == 1
        assert data["packs"][0]["delta"] == 0.2

    def test_week_over_week_stat_model(self) -> None:
        """WeekOverWeekStat accepts valid data."""
        stat = WeekOverWeekStat(
            metric_type=OutcomeMetricType.SUCCESS_RATE,
            current_week_avg=0.9,
            previous_week_avg=0.7,
            pct_change=28.57,
        )
        assert stat.pct_change == 28.57

    def test_failure_mode_stat_model(self) -> None:
        """FailureModeStat accepts valid data."""
        fm = FailureModeStat(failure_class="timeout", count=42)
        assert fm.count == 42
