from __future__ import annotations

from fastapi.testclient import TestClient

from agent33.compatibility.recommendations import recommend_resources
from agent33.compatibility.reports import (
    CompatibilityOutcome,
    CompatibilityReport,
    CompatibilityReportStore,
    set_compatibility_report_store,
)
from agent33.main import app
from agent33.resources.manifest import ResourceKind, ResourceManifest
from agent33.resources.service import ResourceService, set_resource_service
from agent33.security.auth import create_access_token


def _client() -> TestClient:
    token = create_access_token("compat-user", scopes=["workflows:read"], tenant_id="tenant-a")
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def _resource_service() -> ResourceService:
    return ResourceService(
        [
            ResourceManifest(
                id="workflow.review",
                name="Review Workflow",
                version="1.0.0",
                kind=ResourceKind.WORKFLOW,
            ),
            ResourceManifest(
                id="workflow.audit",
                name="Audit Workflow",
                version="1.0.0",
                kind=ResourceKind.WORKFLOW,
            ),
        ]
    )


def test_recommend_resources_prefers_successful_compatibility_history() -> None:
    reports = CompatibilityReportStore()
    reports.record(
        CompatibilityReport(
            report_id="r1",
            provider="openrouter",
            model="large",
            resource_id="workflow.audit",
            outcome=CompatibilityOutcome.SUCCESS,
        )
    )

    result = recommend_resources(
        resource_service=_resource_service(),
        reports=reports,
        model="large",
        provider="openrouter",
    )

    assert result.items[0].resource.id == "workflow.audit"
    assert "compatible success history" in result.items[0].reasons


def test_resource_recommendations_endpoint_returns_ranked_items() -> None:
    service = _resource_service()
    reports = CompatibilityReportStore()
    reports.record(
        CompatibilityReport(
            report_id="r1",
            provider="openrouter",
            model="large",
            resource_id="workflow.review",
            outcome=CompatibilityOutcome.SUCCESS,
        )
    )
    set_resource_service(service)
    set_compatibility_report_store(reports)

    response = _client().get(
        "/v1/compatibility/recommendations/resources",
        params={"model": "large", "provider": "openrouter"},
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["resource"]["id"] == "workflow.review"
