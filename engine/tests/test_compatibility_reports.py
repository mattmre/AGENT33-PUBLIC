from __future__ import annotations

from fastapi.testclient import TestClient

from agent33.api.routes.compatibility import router
from agent33.compatibility.reports import (
    CompatibilityOutcome,
    CompatibilityReport,
    CompatibilityReportStore,
    set_compatibility_report_store,
)
from agent33.main import app
from agent33.security.auth import create_access_token


def _client() -> TestClient:
    token = create_access_token(
        "compat-user",
        scopes=["workflows:read", "tools:execute"],
        tenant_id="tenant-a",
    )
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def setup_function() -> None:
    set_compatibility_report_store(CompatibilityReportStore())


def test_compatibility_report_store_filters_reports() -> None:
    store = CompatibilityReportStore()
    store.record(
        CompatibilityReport(
            report_id="r1",
            model="gpt-4.1-mini",
            provider="openrouter",
            resource_id="pack.core-ops",
            outcome=CompatibilityOutcome.SUCCESS,
        )
    )
    store.record(
        CompatibilityReport(
            report_id="r2",
            model="local-small",
            provider="ollama",
            resource_id="skill.review",
            outcome=CompatibilityOutcome.FAILED,
            failure_mode="context_length",
        )
    )

    assert [report.report_id for report in store.list_reports(provider="ollama")] == ["r2"]
    assert [report.report_id for report in store.list_reports(resource_id="pack.core-ops")] == [
        "r1"
    ]


def test_compatibility_routes_registered() -> None:
    paths = {route.path for route in router.routes}

    assert "/v1/compatibility/reports" in paths or "/reports" in paths


def test_compatibility_report_endpoints_record_and_list_reports() -> None:
    client = _client()

    response = client.post(
        "/v1/compatibility/reports",
        json={
            "report_id": "report-1",
            "run_id": "run-1",
            "model": "gpt-4.1-mini",
            "provider": "openrouter",
            "resource_id": "workflow.review",
            "outcome": "degraded",
            "degraded_mode": "required larger context",
            "required_hints": ["increase-context"],
            "token_count": 1024,
            "cost_usd": 0.02,
            "latency_ms": 1200,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "degraded"
    assert body["required_hints"] == ["increase-context"]

    list_response = client.get("/v1/compatibility/reports", params={"provider": "openrouter"})
    assert list_response.status_code == 200
    assert list_response.json()[0]["report_id"] == "report-1"
