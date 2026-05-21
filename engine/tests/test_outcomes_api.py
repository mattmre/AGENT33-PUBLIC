"""Phase 30 Stage 1 tests for outcomes backend contracts."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from agent33.api.routes import outcomes as outcomes_mod
from agent33.evaluation.ppack_ab_persistence import PPackABPersistence
from agent33.evaluation.ppack_ab_service import PPackABService
from agent33.main import app
from agent33.outcomes.service import OutcomesService
from agent33.security.auth import create_access_token


def _client(scopes: list[str], *, tenant_id: str = "tenant-a") -> TestClient:
    token = create_access_token("outcomes-user", scopes=scopes, tenant_id=tenant_id)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture(autouse=True)
def reset_outcomes_service() -> None:
    """Ensure each test starts with a clean, persistence-free _service.

    Uses ``outcomes_mod._service`` (module attribute access) rather than
    a captured import binding so that ``set_outcomes_service()`` replacements
    are always visible.  Temporarily removes ``app.state.outcomes_service``
    so the route helper ``get_outcomes_service`` falls back to ``_service``.

    Replaces the module-level ``_service`` with a fresh ``OutcomesService()``
    (no persistence) to avoid inheriting a closed SQLite connection from a
    prior lifespan teardown (P72 fix).
    """
    saved_service = outcomes_mod._service
    outcomes_mod._service = OutcomesService()
    saved_ab_service = outcomes_mod._ppack_ab_service
    outcomes_mod._ppack_ab_service = PPackABService(
        outcomes_service=outcomes_mod._service,
        persistence=PPackABPersistence(":memory:"),
    )
    had_attr = hasattr(app.state, "outcomes_service")
    saved_state = getattr(app.state, "outcomes_service", None)
    had_ab_attr = hasattr(app.state, "ppack_ab_service")
    saved_ab_state = getattr(app.state, "ppack_ab_service", None)
    if had_attr:
        delattr(app.state, "outcomes_service")
    if had_ab_attr:
        delattr(app.state, "ppack_ab_service")
    yield
    outcomes_mod._ppack_ab_service.close()
    outcomes_mod._service = saved_service
    outcomes_mod._ppack_ab_service = saved_ab_service
    if had_attr:
        app.state.outcomes_service = saved_state
    elif hasattr(app.state, "outcomes_service"):
        delattr(app.state, "outcomes_service")
    if had_ab_attr:
        app.state.ppack_ab_service = saved_ab_state
    elif hasattr(app.state, "ppack_ab_service"):
        delattr(app.state, "ppack_ab_service")


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
def tenant_b_writer() -> TestClient:
    return _client(["outcomes:read", "outcomes:write"], tenant_id="tenant-b")


@pytest.fixture
def anonymous_client() -> TestClient:
    return TestClient(app)


def test_outcomes_endpoints_require_auth(anonymous_client: TestClient) -> None:
    response = anonymous_client.get("/v1/outcomes/events")
    assert response.status_code == 401


def test_outcome_launch_evaluate_endpoint_returns_friction_signals(
    reader_client: TestClient,
) -> None:
    response = reader_client.post(
        "/v1/outcomes/launch/evaluate",
        json={"objective": "Build it", "preferred_model": "recommended"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["recommendation"]["scale"] == "project_build"
    assert body["readiness"] == "blocked"
    assert body["friction_score"] == 65
    assert [signal["id"] for signal in body["signals"]] == [
        "objective-too-thin",
        "missing-project-context",
        "missing-constraints",
        "model-not-selected",
    ]


def test_outcome_launch_guide_endpoint_returns_missing_answers_and_plan_preview(
    reader_client: TestClient,
) -> None:
    response = reader_client.post(
        "/v1/outcomes/launch/guide",
        json={"objective": "Build it", "preferred_model": "recommended"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["runnable"] is False
    assert body["next_action"] == "collect_missing_answers"
    assert [question["id"] for question in body["missing_answers"]] == [
        "clarify-objective",
        "name-project",
        "capture-constraints",
        "resolve-model",
    ]
    assert body["plan_preview"]["workflow_id"] == "github.pr-review"
    assert body["plan_preview"]["task_class"] == "coding"
    assert body["plan_preview"]["model_routing_path"] == "/v1/model-health/task-routing"
    assert len(body["plan_preview"]["steps"]) == 3


def test_outcomes_scope_enforcement(
    reader_client: TestClient, no_scope_client: TestClient
) -> None:
    write_response = reader_client.post(
        "/v1/outcomes/events",
        json={
            "domain": "delivery",
            "event_type": "deploy",
            "metric_type": "success_rate",
            "value": 0.9,
        },
    )
    assert write_response.status_code == 403
    assert "outcomes:write" in write_response.json()["detail"]

    read_response = no_scope_client.get("/v1/outcomes/events")
    assert read_response.status_code == 403
    assert "outcomes:read" in read_response.json()["detail"]


def test_events_are_tenant_scoped(writer_client: TestClient, tenant_b_writer: TestClient) -> None:
    writer_client.post(
        "/v1/outcomes/events",
        json={
            "domain": "delivery",
            "event_type": "deploy",
            "metric_type": "success_rate",
            "value": 0.8,
        },
    )
    tenant_b_writer.post(
        "/v1/outcomes/events",
        json={
            "domain": "delivery",
            "event_type": "deploy",
            "metric_type": "success_rate",
            "value": 0.2,
        },
    )

    tenant_a_events = writer_client.get("/v1/outcomes/events").json()
    tenant_b_events = tenant_b_writer.get("/v1/outcomes/events").json()
    assert len(tenant_a_events) == 1
    assert len(tenant_b_events) == 1
    assert tenant_a_events[0]["tenant_id"] == "tenant-a"
    assert tenant_b_events[0]["tenant_id"] == "tenant-b"


def test_list_events_supports_domain_and_event_filters(writer_client: TestClient) -> None:
    writer_client.post(
        "/v1/outcomes/events",
        json={
            "domain": "delivery",
            "event_type": "deploy",
            "metric_type": "success_rate",
            "value": 0.8,
        },
    )
    writer_client.post(
        "/v1/outcomes/events",
        json={
            "domain": "support",
            "event_type": "ticket_closed",
            "metric_type": "quality_score",
            "value": 0.6,
        },
    )

    response = writer_client.get(
        "/v1/outcomes/events",
        params={"domain": "delivery", "event_type": "deploy"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["domain"] == "delivery"
    assert payload[0]["event_type"] == "deploy"


def test_trend_direction_values_are_deterministic(writer_client: TestClient) -> None:
    base = datetime.now(UTC) - timedelta(hours=1)
    improving_values = [0.40, 0.45, 0.80, 0.90]
    declining_values = [0.90, 0.80, 0.45, 0.40]

    for idx, value in enumerate(improving_values):
        writer_client.post(
            "/v1/outcomes/events",
            json={
                "domain": "delivery",
                "event_type": "deploy",
                "metric_type": "success_rate",
                "value": value,
                "occurred_at": (base + timedelta(minutes=idx)).isoformat(),
            },
        )
    for idx, value in enumerate(declining_values):
        writer_client.post(
            "/v1/outcomes/events",
            json={
                "domain": "qa",
                "event_type": "test_run",
                "metric_type": "success_rate",
                "value": value,
                "occurred_at": (base + timedelta(minutes=10 + idx)).isoformat(),
            },
        )

    improving = writer_client.get(
        "/v1/outcomes/trends/success_rate",
        params={"domain": "delivery", "window": 4},
    )
    declining = writer_client.get(
        "/v1/outcomes/trends/success_rate",
        params={"domain": "qa", "window": 4},
    )
    stable = writer_client.get(
        "/v1/outcomes/trends/success_rate",
        params={"domain": "unknown-domain", "window": 4},
    )

    assert improving.status_code == 200
    assert improving.json()["direction"] == "improving"
    assert declining.status_code == 200
    assert declining.json()["direction"] == "declining"
    assert stable.status_code == 200
    assert stable.json()["direction"] == "stable"


def test_dashboard_contract(writer_client: TestClient, tenant_b_writer: TestClient) -> None:
    writer_client.post(
        "/v1/outcomes/events",
        json={
            "domain": "delivery",
            "event_type": "deploy",
            "metric_type": "success_rate",
            "value": 0.85,
        },
    )
    writer_client.post(
        "/v1/outcomes/events",
        json={
            "domain": "delivery",
            "event_type": "latency_sample",
            "metric_type": "latency_ms",
            "value": 120.0,
        },
    )
    tenant_b_writer.post(
        "/v1/outcomes/events",
        json={
            "domain": "delivery",
            "event_type": "deploy",
            "metric_type": "success_rate",
            "value": 0.10,
        },
    )

    response = writer_client.get(
        "/v1/outcomes/dashboard",
        params={"window": 10, "recent_limit": 5},
    )
    assert response.status_code == 200
    payload = response.json()
    assert {"trends", "recent_events", "summary"} <= payload.keys()

    summary = payload["summary"]
    assert summary["total_events"] == 2
    assert summary["domains"] == ["delivery"]
    assert set(summary["event_types"]) == {"deploy", "latency_sample"}
    assert summary["metric_counts"]["success_rate"] == 1
    assert summary["metric_counts"]["latency_ms"] == 1

    trends = payload["trends"]
    assert len(trends) == 5
    assert {item["metric_type"] for item in trends} == {
        "success_rate",
        "quality_score",
        "latency_ms",
        "cost_usd",
        "failure_class",
    }
    assert all(item["direction"] in {"improving", "stable", "declining"} for item in trends)

    recent_events = payload["recent_events"]
    assert len(recent_events) == 2
    assert all(event["tenant_id"] == "tenant-a" for event in recent_events)


def test_ppack_assignment_and_report_endpoints(writer_client: TestClient) -> None:
    assign_response = writer_client.post(
        "/v1/outcomes/ppack-v3/assignments",
        json={"session_id": "session-1"},
    )
    assert assign_response.status_code == 201
    assignment = assign_response.json()
    assert assignment["session_id"] == "session-1"
    assert assignment["variant"] in {"control", "treatment"}

    writer_client.post(
        "/v1/outcomes/events",
        json={
            "domain": "delivery",
            "event_type": "invoke",
            "metric_type": "success_rate",
            "value": 1.0 if assignment["variant"] == "control" else 0.0,
            "metadata": {
                "session_id": "session-1",
                "ppack_variant": assignment["variant"],
            },
        },
    )

    second_assign = writer_client.post(
        "/v1/outcomes/ppack-v3/assignments",
        json={"session_id": "session-2"},
    ).json()
    writer_client.post(
        "/v1/outcomes/events",
        json={
            "domain": "delivery",
            "event_type": "invoke",
            "metric_type": "success_rate",
            "value": 1.0 if second_assign["variant"] == "control" else 0.0,
            "metadata": {
                "session_id": "session-2",
                "ppack_variant": second_assign["variant"],
            },
        },
    )

    report_response = writer_client.post(
        "/v1/outcomes/ppack-v3/report",
        json={"domain": "delivery", "metric_types": ["success_rate"]},
    )
    assert report_response.status_code == 200
    report = report_response.json()
    assert report["experiment_key"] == "ppack_v3"
    assert report["domain"] == "delivery"
    assert report["since"] is not None
    assert report["until"] is not None
    assert report["github_issue"]["created"] is False
    assert report["markdown"].startswith("# P-PACK v3 A/B Report")

    fetch_response = writer_client.get(f"/v1/outcomes/ppack-v3/reports/{report['report_id']}")
    assert fetch_response.status_code == 200
    assert fetch_response.json()["report_id"] == report["report_id"]


def test_ppack_report_endpoint_requires_write_scope(
    reader_client: TestClient,
) -> None:
    response = reader_client.post(
        "/v1/outcomes/ppack-v3/report",
        json={"domain": "delivery", "metric_types": ["success_rate"]},
    )
    assert response.status_code == 403
    assert "outcomes:write" in response.json()["detail"]


def test_ppack_variant_resolution_uses_persisted_assignment(
    writer_client: TestClient,
) -> None:
    """Variant resolution should trust persisted assignments over caller metadata."""
    assign_response = writer_client.post(
        "/v1/outcomes/ppack-v3/assignments",
        json={"session_id": "session-integrity"},
    )
    assert assign_response.status_code == 201
    assignment = assign_response.json()
    true_variant = assignment["variant"]
    spoofed_variant = "treatment" if true_variant == "control" else "control"

    writer_client.post(
        "/v1/outcomes/events",
        json={
            "domain": "delivery",
            "event_type": "invoke",
            "metric_type": "success_rate",
            "value": 1.0,
            "metadata": {
                "session_id": "session-integrity",
                "ppack_variant": spoofed_variant,
            },
        },
    )

    report_response = writer_client.post(
        "/v1/outcomes/ppack-v3/report",
        json={"domain": "delivery", "metric_types": ["success_rate"]},
    )
    assert report_response.status_code == 200
    report = report_response.json()
    comparisons = report["comparisons"]
    success_comparison = next(c for c in comparisons if c["metric_type"] == "success_rate")

    if true_variant == "control":
        assert success_comparison["control_count"] == 1
        assert success_comparison["treatment_count"] == 0
    else:
        assert success_comparison["control_count"] == 0
        assert success_comparison["treatment_count"] == 1


def test_ppack_assignment_sqlite_error_returns_503(
    writer_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Assignment persistence failures should return 503."""
    from agent33.api.routes import outcomes as outcomes_mod

    def raise_sqlite_error(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(
        outcomes_mod._ppack_ab_service._persistence,
        "save_assignment",
        raise_sqlite_error,
    )

    response = writer_client.post(
        "/v1/outcomes/ppack-v3/assignments",
        json={"session_id": "session-error"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "P-PACK v3 persistence error"


def test_ppack_get_assignment_sqlite_error_returns_503(
    writer_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Assignment retrieval persistence failures should return 503."""
    from agent33.api.routes import outcomes as outcomes_mod

    def raise_sqlite_error(*args, **kwargs):
        raise sqlite3.DatabaseError("disk I/O error")

    monkeypatch.setattr(
        outcomes_mod._ppack_ab_service._persistence,
        "get_assignment",
        raise_sqlite_error,
    )

    response = writer_client.get("/v1/outcomes/ppack-v3/assignments/session-test")
    assert response.status_code == 503
    assert response.json()["detail"] == "P-PACK v3 persistence error"


def test_ppack_get_report_sqlite_error_returns_503(
    writer_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Report retrieval persistence failures should return 503."""
    from agent33.api.routes import outcomes as outcomes_mod

    def raise_sqlite_error(*args, **kwargs):
        raise sqlite3.IntegrityError("constraint violation")

    monkeypatch.setattr(
        outcomes_mod._ppack_ab_service._persistence,
        "get_report",
        raise_sqlite_error,
    )

    response = writer_client.get("/v1/outcomes/ppack-v3/reports/report-test")
    assert response.status_code == 503
    assert response.json()["detail"] == "P-PACK v3 persistence error"


def test_ppack_get_report_is_tenant_scoped(
    writer_client: TestClient,
    tenant_b_writer: TestClient,
) -> None:
    assign_response = writer_client.post(
        "/v1/outcomes/ppack-v3/assignments",
        json={"session_id": "session-tenant-a"},
    )
    assert assign_response.status_code == 201
    assignment = assign_response.json()
    writer_client.post(
        "/v1/outcomes/events",
        json={
            "domain": "delivery",
            "event_type": "invoke",
            "metric_type": "success_rate",
            "value": 1.0,
            "metadata": {
                "session_id": "session-tenant-a",
                "ppack_variant": assignment["variant"],
            },
        },
    )
    report_response = writer_client.post(
        "/v1/outcomes/ppack-v3/report",
        json={"domain": "delivery", "metric_types": ["success_rate"]},
    )
    assert report_response.status_code == 200
    report_id = report_response.json()["report_id"]

    response = tenant_b_writer.get(f"/v1/outcomes/ppack-v3/reports/{report_id}")
    assert response.status_code == 404
