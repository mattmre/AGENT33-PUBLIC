from __future__ import annotations

from fastapi.testclient import TestClient

from agent33.compatibility.reports import (
    CompatibilityOutcome,
    CompatibilityReport,
    CompatibilityReportStore,
    set_compatibility_report_store,
)
from agent33.compatibility.routing import (
    CompatibilityRouteRequest,
    ModelRouteCandidate,
    choose_compatible_route,
)
from agent33.main import app
from agent33.security.auth import create_access_token


def _client() -> TestClient:
    token = create_access_token("compat-user", scopes=["workflows:read"], tenant_id="tenant-a")
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def setup_function() -> None:
    set_compatibility_report_store(CompatibilityReportStore())


def test_compatibility_routing_prefers_success_history() -> None:
    store = CompatibilityReportStore()
    store.record(
        CompatibilityReport(
            report_id="r1",
            provider="openrouter",
            model="large",
            resource_id="workflow.review",
            outcome=CompatibilityOutcome.SUCCESS,
        )
    )
    store.record(
        CompatibilityReport(
            report_id="r2",
            provider="ollama",
            model="small",
            resource_id="workflow.review",
            outcome=CompatibilityOutcome.FAILED,
        )
    )

    decision = choose_compatible_route(
        CompatibilityRouteRequest(
            task_risk="high",
            resource_id="workflow.review",
            required_context=16000,
            candidates=[
                ModelRouteCandidate(provider="ollama", model="small", context_length=8000),
                ModelRouteCandidate(provider="openrouter", model="large", context_length=32000),
            ],
        ),
        reports=store,
    )

    assert decision.model == "large"
    assert "prior successful runs" in decision.reasons


def test_compatibility_routing_endpoint_returns_preview_decision() -> None:
    store = CompatibilityReportStore()
    store.record(
        CompatibilityReport(
            report_id="r1",
            provider="openrouter",
            model="large",
            resource_id="pack.core-ops",
            outcome=CompatibilityOutcome.SUCCESS,
        )
    )
    set_compatibility_report_store(store)
    client = _client()

    response = client.post(
        "/v1/compatibility/routing/preview",
        json={
            "task_risk": "normal",
            "resource_id": "pack.core-ops",
            "required_context": 4000,
            "candidates": [
                {"provider": "ollama", "model": "small", "context_length": 8000, "cost_rank": 1},
                {
                    "provider": "openrouter",
                    "model": "large",
                    "context_length": 32000,
                    "cost_rank": 3,
                },
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["model"] == "large"
