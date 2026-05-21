"""Tests for P68-Lite monitoring health endpoint (architectural decision #15).

Verifies:
1. `OutcomesService.health_check()` returns "ok" when a recent event exists.
2. `OutcomesService.health_check()` returns "stale" with hours count when
   the most recent event is older than the threshold.
3. `OutcomesService.health_check()` returns "stale" with null hours when no
   events have ever been recorded.
4. `GET /v1/outcomes/health` is reachable without authentication and delegates
   to the service correctly.
5. The endpoint returns "stale" (null) when the service has no events.
6. The endpoint returns "stale" with an hours count when all events are old.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from agent33.api.routes import outcomes as outcomes_mod
from agent33.evaluation.ppack_ab_persistence import PPackABPersistence
from agent33.evaluation.ppack_ab_service import PPackABService
from agent33.main import app
from agent33.outcomes.models import OutcomeEventCreate, OutcomeMetricType
from agent33.outcomes.persistence import OutcomePersistence
from agent33.outcomes.service import OutcomesService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_outcomes_module_state() -> None:
    """Isolate each test: fresh service with no persistence, no app.state leak."""
    saved_service = outcomes_mod._service
    saved_ab = outcomes_mod._ppack_ab_service
    fresh_svc = OutcomesService()
    outcomes_mod._service = fresh_svc
    outcomes_mod._ppack_ab_service = PPackABService(
        outcomes_service=fresh_svc,
        persistence=PPackABPersistence(":memory:"),
    )
    had_svc = hasattr(app.state, "outcomes_service")
    saved_state_svc = getattr(app.state, "outcomes_service", None)
    if had_svc:
        delattr(app.state, "outcomes_service")
    yield
    outcomes_mod._service = saved_service
    outcomes_mod._ppack_ab_service = saved_ab
    if had_svc:
        app.state.outcomes_service = saved_state_svc
    elif hasattr(app.state, "outcomes_service"):
        delattr(app.state, "outcomes_service")


@pytest.fixture()
def svc() -> OutcomesService:
    """Return the current module-level service (already fresh per autouse fixture)."""
    return outcomes_mod._service


@pytest.fixture()
def anon_client() -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# Unit tests: OutcomesService.health_check()
# ---------------------------------------------------------------------------


def test_health_check_ok_when_recent_event(svc: OutcomesService) -> None:
    """Status is 'ok' when the most recent event was recorded within the last 24 h."""
    svc.record_event(
        tenant_id="t1",
        event=OutcomeEventCreate(
            domain="agent-x",
            event_type="invoke",
            metric_type=OutcomeMetricType.SUCCESS_RATE,
            value=1.0,
            occurred_at=datetime.now(UTC) - timedelta(hours=1),
        ),
    )

    result = svc.health_check()

    assert result["status"] == "ok"
    assert "hours_since_last_event" not in result


def test_health_check_stale_when_event_older_than_threshold(svc: OutcomesService) -> None:
    """Status is 'stale' with hours count when the last event is > threshold hours old."""
    svc.record_event(
        tenant_id="t1",
        event=OutcomeEventCreate(
            domain="agent-x",
            event_type="invoke",
            metric_type=OutcomeMetricType.SUCCESS_RATE,
            value=1.0,
            occurred_at=datetime.now(UTC) - timedelta(hours=30),
        ),
    )

    result = svc.health_check(alert_threshold_hours=24.0)

    assert result["status"] == "stale"
    hours = result["hours_since_last_event"]
    assert hours is not None
    assert isinstance(hours, float)
    # Should be approximately 30 h (within 1 h tolerance for test speed)
    assert 29.0 <= hours <= 31.0


def test_health_check_stale_null_when_no_events(svc: OutcomesService) -> None:
    """Status is 'stale' with null hours when the table has never had any events."""
    result = svc.health_check()

    assert result["status"] == "stale"
    assert result["hours_since_last_event"] is None


def test_health_check_uses_persisted_events_after_restart(tmp_path) -> None:
    """Persisted history should keep health green after an in-memory restart."""
    db_path = tmp_path / "outcomes.db"
    writer_persistence = OutcomePersistence(db_path)
    writer_service = OutcomesService(persistence=writer_persistence)
    writer_service.record_event(
        tenant_id="tenant-a",
        event=OutcomeEventCreate(
            domain="agent-x",
            event_type="invoke",
            metric_type=OutcomeMetricType.SUCCESS_RATE,
            value=1.0,
            occurred_at=datetime.now(UTC) - timedelta(minutes=15),
        ),
    )
    writer_persistence.close()

    restarted_service = OutcomesService(persistence=OutcomePersistence(db_path))

    result = restarted_service.health_check()

    assert result["status"] == "ok"
    assert "hours_since_last_event" not in result


def test_health_check_uses_most_recent_event_across_tenants(svc: OutcomesService) -> None:
    """The most recent event wins, even if it belongs to a different tenant."""
    # Old event for tenant-a
    svc.record_event(
        tenant_id="tenant-a",
        event=OutcomeEventCreate(
            domain="agent-x",
            event_type="invoke",
            metric_type=OutcomeMetricType.SUCCESS_RATE,
            value=1.0,
            occurred_at=datetime.now(UTC) - timedelta(hours=30),
        ),
    )
    # Recent event for tenant-b
    svc.record_event(
        tenant_id="tenant-b",
        event=OutcomeEventCreate(
            domain="agent-y",
            event_type="invoke",
            metric_type=OutcomeMetricType.SUCCESS_RATE,
            value=1.0,
            occurred_at=datetime.now(UTC) - timedelta(hours=1),
        ),
    )

    result = svc.health_check(alert_threshold_hours=24.0)

    # The tenant-b event is recent — should be ok
    assert result["status"] == "ok"


def test_health_check_threshold_boundary(svc: OutcomesService) -> None:
    """An event exactly at the boundary (=threshold) is considered 'ok'."""
    # Record an event exactly at the threshold (24 h ago)
    svc.record_event(
        tenant_id="t1",
        event=OutcomeEventCreate(
            domain="agent-x",
            event_type="invoke",
            metric_type=OutcomeMetricType.SUCCESS_RATE,
            value=1.0,
            occurred_at=datetime.now(UTC) - timedelta(hours=24),
        ),
    )

    result = svc.health_check(alert_threshold_hours=24.1)

    # delta_hours == 24.0 satisfies delta_hours <= 24.1
    assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# Integration tests: GET /v1/outcomes/health endpoint
# ---------------------------------------------------------------------------


def test_health_endpoint_no_auth_required(anon_client: TestClient) -> None:
    """The health endpoint must be accessible without authentication."""
    response = anon_client.get("/v1/outcomes/health")
    # Must not be 401 or 403
    assert response.status_code == 200


def test_health_endpoint_returns_stale_null_when_no_events(anon_client: TestClient) -> None:
    """Endpoint returns stale/null when the service has never recorded an event."""
    response = anon_client.get("/v1/outcomes/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "stale"
    assert payload["hours_since_last_event"] is None


def test_health_endpoint_returns_ok_when_recent_event(anon_client: TestClient) -> None:
    """Endpoint returns ok after a recent event is recorded."""
    svc = outcomes_mod._service
    svc.record_event(
        tenant_id="t1",
        event=OutcomeEventCreate(
            domain="agent-x",
            event_type="invoke",
            metric_type=OutcomeMetricType.SUCCESS_RATE,
            value=1.0,
            occurred_at=datetime.now(UTC) - timedelta(minutes=5),
        ),
    )

    response = anon_client.get("/v1/outcomes/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "hours_since_last_event" not in payload


def test_health_endpoint_returns_stale_with_hours_when_events_are_old(
    anon_client: TestClient,
) -> None:
    """Endpoint returns stale with hours count when last event is > 24 h old."""
    svc = outcomes_mod._service
    svc.record_event(
        tenant_id="t1",
        event=OutcomeEventCreate(
            domain="agent-x",
            event_type="invoke",
            metric_type=OutcomeMetricType.SUCCESS_RATE,
            value=1.0,
            occurred_at=datetime.now(UTC) - timedelta(hours=48),
        ),
    )

    response = anon_client.get("/v1/outcomes/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "stale"
    hours = payload["hours_since_last_event"]
    assert hours is not None
    assert isinstance(hours, float)
    assert 47.0 <= hours <= 49.0


def test_health_endpoint_uses_app_state_service(anon_client: TestClient) -> None:
    """When app.state.outcomes_service is set, the endpoint uses it (not the module fallback)."""
    app_state_svc = OutcomesService()
    app_state_svc.record_event(
        tenant_id="t1",
        event=OutcomeEventCreate(
            domain="agent-x",
            event_type="invoke",
            metric_type=OutcomeMetricType.SUCCESS_RATE,
            value=1.0,
            occurred_at=datetime.now(UTC) - timedelta(minutes=5),
        ),
    )
    # Module-level service has no events (stale)
    assert outcomes_mod._service._events == {}

    app.state.outcomes_service = app_state_svc
    try:
        response = anon_client.get("/v1/outcomes/health")
        assert response.status_code == 200
        payload = response.json()
        # The app.state service has a recent event — should be ok
        assert payload["status"] == "ok"
    finally:
        delattr(app.state, "outcomes_service")
