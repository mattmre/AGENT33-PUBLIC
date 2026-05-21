"""Tests for MCP proxy management REST API endpoints (Phase 45)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from agent33.api.routes.mcp_proxy import router, set_proxy_manager
from agent33.mcp_server.proxy_child import ProxyToolDefinition
from agent33.mcp_server.proxy_manager import ProxyManager
from agent33.mcp_server.proxy_models import ProxyServerConfig


class _FakeAuthMiddleware(BaseHTTPMiddleware):
    """Inject a fake authenticated user with admin scopes."""

    async def dispatch(self, request: Any, call_next: Any) -> Any:
        request.state.user = MagicMock(
            sub="admin@test.com",
            scopes=["admin", "agents:read", "tools:execute"],
            tenant_id="t-001",
        )
        return await call_next(request)


def _create_test_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(_FakeAuthMiddleware)
    app.include_router(router)
    return app


@pytest.fixture
def proxy_manager() -> ProxyManager:
    return ProxyManager()


@pytest.fixture
def client(proxy_manager: ProxyManager) -> TestClient:
    set_proxy_manager(proxy_manager)
    app = _create_test_app()
    return TestClient(app)


def _run(awaitable: Any) -> Any:
    return asyncio.run(awaitable)


class TestListServers:
    """GET /v1/mcp/proxy/servers."""

    def test_empty_fleet(self, client: TestClient) -> None:
        resp = client.get("/v1/mcp/proxy/servers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["servers"] == []
        assert data["total"] == 0
        assert data["healthy"] == 0

    def test_with_servers(self, client: TestClient, proxy_manager: ProxyManager) -> None:
        _run(proxy_manager.add_server(ProxyServerConfig(id="s1", command="echo")))
        resp = client.get("/v1/mcp/proxy/servers")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["servers"]) == 1
        assert data["servers"][0]["id"] == "s1"
        assert data["servers"][0]["state"] == "healthy"
        assert data["healthy"] == 1


class TestGetServer:
    """GET /v1/mcp/proxy/servers/{server_id}."""

    def test_existing_server(self, client: TestClient, proxy_manager: ProxyManager) -> None:
        _run(proxy_manager.add_server(ProxyServerConfig(id="s1", command="echo")))
        resp = client.get("/v1/mcp/proxy/servers/s1")
        assert resp.status_code == 200
        assert resp.json()["id"] == "s1"

    def test_nonexistent_server(self, client: TestClient) -> None:
        resp = client.get("/v1/mcp/proxy/servers/nope")
        assert resp.status_code == 404


class TestAddServer:
    """POST /v1/mcp/proxy/servers."""

    def test_add_new_server(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/mcp/proxy/servers",
            json={"id": "new-server", "command": "echo"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "new-server"
        assert data["state"] == "healthy"

    def test_add_duplicate_returns_conflict(
        self, client: TestClient, proxy_manager: ProxyManager
    ) -> None:
        _run(proxy_manager.add_server(ProxyServerConfig(id="dup", command="echo")))
        resp = client.post(
            "/v1/mcp/proxy/servers",
            json={"id": "dup", "command": "echo"},
        )
        assert resp.status_code == 409


class TestRemoveServer:
    """DELETE /v1/mcp/proxy/servers/{server_id}."""

    def test_remove_existing(self, client: TestClient, proxy_manager: ProxyManager) -> None:
        _run(proxy_manager.add_server(ProxyServerConfig(id="rm-me", command="echo")))
        resp = client.delete("/v1/mcp/proxy/servers/rm-me")
        assert resp.status_code == 200
        assert resp.json()["status"] == "removed"

    def test_remove_nonexistent(self, client: TestClient) -> None:
        resp = client.delete("/v1/mcp/proxy/servers/nope")
        assert resp.status_code == 404


class TestRestartServer:
    """POST /v1/mcp/proxy/servers/{server_id}/restart."""

    def test_restart_existing(self, client: TestClient, proxy_manager: ProxyManager) -> None:
        _run(proxy_manager.add_server(ProxyServerConfig(id="restart-me", command="echo")))
        resp = client.post("/v1/mcp/proxy/servers/restart-me/restart")
        assert resp.status_code == 200
        assert resp.json()["state"] == "healthy"

    def test_restart_nonexistent(self, client: TestClient) -> None:
        resp = client.post("/v1/mcp/proxy/servers/nope/restart")
        assert resp.status_code == 404


class TestListProxyTools:
    """GET /v1/mcp/proxy/tools."""

    def test_lists_aggregated_tools(self, client: TestClient, proxy_manager: ProxyManager) -> None:
        handle = _run(
            proxy_manager.add_server(ProxyServerConfig(id="fs", command="echo", tool_prefix="fs"))
        )
        handle.register_tools(
            [
                ProxyToolDefinition(name="read_file", description="Read"),
            ]
        )
        resp = client.get("/v1/mcp/proxy/tools")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["tools"][0]["name"] == "fs__read_file"


class TestFleetHealth:
    """GET /v1/mcp/proxy/health (public endpoint)."""

    def test_health_summary(self, client: TestClient) -> None:
        resp = client.get("/v1/mcp/proxy/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "healthy" in data

    def test_health_skips_refresh_when_disabled(self) -> None:
        async def _unexpected_refresh() -> None:
            raise AssertionError("refresh_health should not be called when disabled")

        manager = ProxyManager(health_check_enabled=False)
        manager.refresh_health = _unexpected_refresh  # type: ignore[method-assign]
        set_proxy_manager(manager)
        app = _create_test_app()
        client = TestClient(app)

        resp = client.get("/v1/mcp/proxy/health")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


class TestManagerNotInitialized:
    """When proxy manager is None, endpoints return 503."""

    def test_503_when_not_initialized(self) -> None:
        set_proxy_manager(None)  # type: ignore[arg-type]
        app = _create_test_app()
        client = TestClient(app)
        resp = client.get("/v1/mcp/proxy/servers")
        assert resp.status_code == 503
