from __future__ import annotations

from datetime import UTC, datetime
from time import monotonic

from fastapi.testclient import TestClient

from agent33.api.routes.doctor import router
from agent33.config import settings
from agent33.main import app
from agent33.operator.models import CheckStatus, DiagnosticCheck, DiagnosticResult
from agent33.operator.service import OperatorService
from agent33.ops.doctor_status import build_doctor_status
from agent33.security.auth import create_access_token


def test_build_doctor_status_normalizes_findings() -> None:
    result = DiagnosticResult(
        overall=CheckStatus.WARNING,
        timestamp=datetime(2026, 5, 5, tzinfo=UTC),
        checks=[
            DiagnosticCheck(
                id="DOC-04",
                category="llm",
                status=CheckStatus.WARNING,
                message="Model provider is not verified",
                remediation="Open model setup",
            )
        ],
    )

    status = build_doctor_status(result)

    assert status.overall == "warning"
    assert status.findings[0].owner == "models"
    assert status.findings[0].fix_action == "Open model setup"
    assert status.findings[0].action_type == "navigate"
    assert status.findings[0].action_target == "models"
    assert status.findings[0].evidence_refs == ("doctor:DOC-04:llm",)


def test_doctor_status_route_is_registered() -> None:
    paths = {route.path for route in router.routes}

    assert "/v1/doctor/status" in paths or "/status" in paths
    assert "/v1/doctor/state-paths" in paths or "/state-paths" in paths


def test_doctor_status_endpoint_returns_aggregated_contract() -> None:
    app.state.operator_service = OperatorService(
        app_state=app.state,
        settings=settings,
        start_time=monotonic(),
    )
    token = create_access_token("doctor-user", scopes=["operator:read"], tenant_id="tenant-a")
    client = TestClient(app, headers={"Authorization": f"Bearer {token}"})

    response = client.get("/v1/doctor/status")

    assert response.status_code == 200
    body = response.json()
    assert body["overall"] in {"ok", "warning", "error"}
    assert isinstance(body["findings"], list)
    expected_keys = {
        "id",
        "category",
        "severity",
        "owner",
        "fix_action",
        "action_type",
        "action_target",
        "evidence_refs",
    }
    assert expected_keys.issubset(body["findings"][0])


def test_doctor_state_paths_endpoint_returns_restart_audit() -> None:
    token = create_access_token("doctor-user", scopes=["operator:read"], tenant_id="tenant-a")
    client = TestClient(app, headers={"Authorization": f"Bearer {token}"})

    response = client.get("/v1/doctor/state-paths")

    assert response.status_code == 200
    body = response.json()
    assert body["overall"] in {"ok", "warning", "error"}
    assert isinstance(body["items"], list)
    p69b = next(item for item in body["items"] if item["id"] == "p69b-paused-invocations")
    assert p69b["status"] == "ok"
    assert p69b["restart_safe"] is True
    assert p69b["root"] == "app_var"
