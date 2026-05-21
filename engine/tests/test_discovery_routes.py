"""Tests for discovery API routes."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from agent33.api.routes.discovery import set_discovery_service
from agent33.discovery.service import (
    SkillDiscoveryMatch,
    ToolDiscoveryMatch,
    WorkflowResolutionMatch,
)
from agent33.main import app
from agent33.security.auth import create_access_token


def _client(scopes: list[str], tenant_id: str = "") -> TestClient:
    token = create_access_token("test-user", scopes=scopes, tenant_id=tenant_id)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture(autouse=True)
def _setup_discovery_service() -> None:
    service = MagicMock()
    service.discover_tools.return_value = [
        ToolDiscoveryMatch(name="shell", description="Run commands", score=9.5, tags=["system"])
    ]
    service.discover_skills.return_value = [
        SkillDiscoveryMatch(
            name="deploy-safely",
            description="Deploy safely",
            score=8.0,
            tags=["deployment"],
            pack="alpha",
        )
    ]
    service.resolve_workflow.return_value = [
        WorkflowResolutionMatch(
            name="release",
            description="Release workflow",
            score=10.0,
            source="runtime",
            tags=["shipping"],
        )
    ]
    set_discovery_service(service)
    yield
    set_discovery_service(None)


class TestDiscoveryRoutesAuth:
    def test_discover_tools_requires_tools_execute(self) -> None:
        response = _client(["agents:read"]).get("/v1/discovery/tools?q=shell")
        assert response.status_code == 403

    def test_resolve_workflow_requires_workflows_read(self) -> None:
        response = _client(["agents:read"]).get("/v1/discovery/workflows/resolve?q=release")
        assert response.status_code == 403


class TestDiscoveryRoutes:
    def test_discover_tools_returns_ranked_matches(self) -> None:
        response = _client(["tools:execute"]).get("/v1/discovery/tools?q=shell")
        assert response.status_code == 200
        body = response.json()
        assert body["query"] == "shell"
        assert body["matches"][0]["name"] == "shell"

    def test_discover_skills_passes_tenant_filter(self) -> None:
        service = MagicMock()
        service.discover_skills.return_value = []
        set_discovery_service(service)

        response = _client(["agents:read"], tenant_id="tenant-a").get(
            "/v1/discovery/skills?q=deploy"
        )

        assert response.status_code == 200
        service.discover_skills.assert_called_once_with("deploy", limit=10, tenant_id="tenant-a")

    def test_discover_skills_allows_admin_without_tenant_filter(self) -> None:
        service = MagicMock()
        service.discover_skills.return_value = []
        set_discovery_service(service)

        response = _client(["admin"]).get("/v1/discovery/skills?q=deploy")

        assert response.status_code == 200
        service.discover_skills.assert_called_once_with("deploy", limit=10, tenant_id=None)

    def test_resolve_workflow_returns_matches(self) -> None:
        response = _client(["workflows:read"], tenant_id="tenant-a").get(
            "/v1/discovery/workflows/resolve?q=release"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["query"] == "release"
        assert body["matches"][0]["source"] == "runtime"

    def test_resolve_workflow_passes_tenant_filter(self) -> None:
        service = MagicMock()
        service.resolve_workflow.return_value = []
        set_discovery_service(service)

        response = _client(["workflows:read"], tenant_id="tenant-a").get(
            "/v1/discovery/workflows/resolve?q=deploy"
        )

        assert response.status_code == 200
        service.resolve_workflow.assert_called_once_with("deploy", limit=10, tenant_id="tenant-a")

    def test_resolve_workflow_allows_admin_without_tenant_filter(self) -> None:
        service = MagicMock()
        service.resolve_workflow.return_value = []
        set_discovery_service(service)

        response = _client(["admin"]).get("/v1/discovery/workflows/resolve?q=deploy")

        assert response.status_code == 200
        service.resolve_workflow.assert_called_once_with("deploy", limit=10, tenant_id=None)
