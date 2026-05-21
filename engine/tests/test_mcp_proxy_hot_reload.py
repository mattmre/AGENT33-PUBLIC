"""Tests for MCP proxy hot-reload endpoints and ProxyManager reload logic (S21)."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from agent33.api.routes.mcp_proxy import router, set_config_path, set_proxy_manager
from agent33.mcp_server.proxy_child import ChildServerState, ProxyToolDefinition
from agent33.mcp_server.proxy_manager import ProxyManager
from agent33.mcp_server.proxy_models import ProxyFleetConfig, ProxyServerConfig


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


def _run(awaitable: Any) -> Any:
    return asyncio.run(awaitable)


def _server_config(
    server_id: str,
    command: str = "echo",
    prefix: str = "",
    enabled: bool = True,
) -> ProxyServerConfig:
    return ProxyServerConfig(
        id=server_id,
        name=f"Server {server_id}",
        command=command,
        tool_prefix=prefix,
        enabled=enabled,
    )


@pytest.fixture
def proxy_manager() -> ProxyManager:
    return ProxyManager()


@pytest.fixture
def client(proxy_manager: ProxyManager) -> TestClient:
    set_proxy_manager(proxy_manager)
    set_config_path("")
    app = _create_test_app()
    return TestClient(app)


# ---------------------------------------------------------------------------
# Fleet restart endpoint: POST /v1/mcp/proxy/restart
# ---------------------------------------------------------------------------


class TestFleetRestart:
    """POST /v1/mcp/proxy/restart -- restarts all enabled servers."""

    def test_fleet_restart_all_succeed(
        self, client: TestClient, proxy_manager: ProxyManager
    ) -> None:
        """All enabled servers are restarted and reported."""
        _run(proxy_manager.add_server(_server_config("s1")))
        _run(proxy_manager.add_server(_server_config("s2")))
        _run(proxy_manager.add_server(_server_config("s3", enabled=False)))

        resp = client.post("/v1/mcp/proxy/restart")
        assert resp.status_code == 200
        data = resp.json()

        assert sorted(data["restarted"]) == ["s1", "s2"]
        assert data["failed"] == []
        assert data["total"] == 2
        assert data["success_count"] == 2
        assert data["failure_count"] == 0

        # Verify all enabled servers are still healthy after restart
        s1 = proxy_manager.get_server("s1")
        s2 = proxy_manager.get_server("s2")
        assert s1 is not None and s1.state == ChildServerState.HEALTHY
        assert s2 is not None and s2.state == ChildServerState.HEALTHY

    def test_fleet_restart_partial_failure(
        self, client: TestClient, proxy_manager: ProxyManager
    ) -> None:
        """When one server fails to start, it appears in 'failed' list."""
        _run(proxy_manager.add_server(_server_config("good")))
        _run(proxy_manager.add_server(_server_config("bad")))

        # Make the 'bad' server's start() raise
        bad_handle = proxy_manager.get_server("bad")
        assert bad_handle is not None

        async def _failing_start() -> None:
            raise RuntimeError("simulated start failure")

        bad_handle.start = _failing_start  # type: ignore[method-assign]

        resp = client.post("/v1/mcp/proxy/restart")
        assert resp.status_code == 200
        data = resp.json()

        assert "good" in data["restarted"]
        assert len(data["failed"]) == 1
        assert data["failed"][0]["id"] == "bad"
        assert "simulated start failure" in data["failed"][0]["error"]
        assert data["success_count"] == 1
        assert data["failure_count"] == 1

    def test_fleet_restart_empty_fleet(self, client: TestClient) -> None:
        """Restarting an empty fleet is a no-op."""
        resp = client.post("/v1/mcp/proxy/restart")
        assert resp.status_code == 200
        data = resp.json()
        assert data["restarted"] == []
        assert data["failed"] == []
        assert data["total"] == 0


# ---------------------------------------------------------------------------
# Config reload endpoint: POST /v1/mcp/proxy/reload-config
# ---------------------------------------------------------------------------


class TestConfigReload:
    """POST /v1/mcp/proxy/reload-config -- re-reads and applies config."""

    def test_reload_add_new_server(self, client: TestClient, proxy_manager: ProxyManager) -> None:
        """New servers in config are added to the fleet."""
        _run(proxy_manager.add_server(_server_config("existing")))

        config = {
            "proxy_servers": [
                {"id": "existing", "name": "Server existing", "command": "echo"},
                {"id": "brand-new", "name": "Brand New", "command": "node"},
            ]
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(config, f)
            config_path = f.name

        try:
            set_config_path(config_path)
            resp = client.post("/v1/mcp/proxy/reload-config")
            assert resp.status_code == 200
            data = resp.json()

            assert "brand-new" in data["added"]
            assert data["removed"] == []
            assert data["errors"] == []

            # Verify the new server exists and is healthy
            handle = proxy_manager.get_server("brand-new")
            assert handle is not None
            assert handle.state == ChildServerState.HEALTHY
        finally:
            os.unlink(config_path)

    def test_reload_remove_server(self, client: TestClient, proxy_manager: ProxyManager) -> None:
        """Servers no longer in config are stopped and removed."""
        _run(proxy_manager.add_server(_server_config("keep")))
        _run(proxy_manager.add_server(_server_config("remove-me")))

        config = {
            "proxy_servers": [
                {"id": "keep", "name": "Server keep", "command": "echo"},
            ]
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(config, f)
            config_path = f.name

        try:
            set_config_path(config_path)
            resp = client.post("/v1/mcp/proxy/reload-config")
            assert resp.status_code == 200
            data = resp.json()

            assert "remove-me" in data["removed"]
            assert proxy_manager.get_server("remove-me") is None
            assert proxy_manager.get_server("keep") is not None
        finally:
            os.unlink(config_path)

    def test_reload_changed_config_triggers_restart(
        self, client: TestClient, proxy_manager: ProxyManager
    ) -> None:
        """When a server's config changes, it is restarted with the new config."""
        _run(proxy_manager.add_server(ProxyServerConfig(id="s1", name="Old Name", command="echo")))

        config = {
            "proxy_servers": [
                {"id": "s1", "name": "New Name", "command": "node"},
            ]
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(config, f)
            config_path = f.name

        try:
            set_config_path(config_path)
            resp = client.post("/v1/mcp/proxy/reload-config")
            assert resp.status_code == 200
            data = resp.json()

            assert "s1" in data["restarted"]
            assert data["unchanged"] == []

            # Verify the config was actually updated
            handle = proxy_manager.get_server("s1")
            assert handle is not None
            assert handle.config.name == "New Name"
            assert handle.config.command == "node"
        finally:
            os.unlink(config_path)

    def test_reload_invalid_config_returns_400(self, client: TestClient) -> None:
        """Invalid JSON in config file returns 400, fleet is untouched."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            f.write("{not valid json!!!")
            config_path = f.name

        try:
            set_config_path(config_path)
            resp = client.post("/v1/mcp/proxy/reload-config")
            assert resp.status_code == 400
            assert "Invalid config" in resp.json()["detail"]
        finally:
            os.unlink(config_path)

    def test_reload_file_not_found_returns_400(self, client: TestClient) -> None:
        """Missing config file returns 400."""
        set_config_path("/nonexistent/path/config.json")
        resp = client.post("/v1/mcp/proxy/reload-config")
        assert resp.status_code == 400
        assert "not found" in resp.json()["detail"]

    def test_reload_no_config_path_returns_400(self, client: TestClient) -> None:
        """No config path configured returns 400."""
        set_config_path("")
        resp = client.post("/v1/mcp/proxy/reload-config")
        assert resp.status_code == 400
        assert "No mcp_proxy_config_path" in resp.json()["detail"]

    def test_reload_unchanged_servers_not_restarted(
        self, client: TestClient, proxy_manager: ProxyManager
    ) -> None:
        """Servers with identical config are left untouched."""
        cfg = ProxyServerConfig(id="stable", name="Stable", command="echo")
        _run(proxy_manager.add_server(cfg))

        # Write identical config
        config = {"proxy_servers": [cfg.model_dump()]}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(config, f)
            config_path = f.name

        try:
            set_config_path(config_path)
            resp = client.post("/v1/mcp/proxy/reload-config")
            assert resp.status_code == 200
            data = resp.json()

            assert data["added"] == []
            assert data["restarted"] == []
            assert data["removed"] == []
            assert "stable" in data["unchanged"]
        finally:
            os.unlink(config_path)


# ---------------------------------------------------------------------------
# Config validation endpoint: POST /v1/mcp/proxy/validate-config
# ---------------------------------------------------------------------------


class TestConfigValidation:
    """POST /v1/mcp/proxy/validate-config -- dry-run config validation."""

    def test_validate_valid_config_returns_diff(
        self, client: TestClient, proxy_manager: ProxyManager
    ) -> None:
        """Valid config shows what would change."""
        _run(proxy_manager.add_server(_server_config("existing")))

        config = {
            "proxy_servers": [
                {"id": "existing", "name": "Server existing", "command": "echo"},
                {"id": "new-one", "name": "New One", "command": "node"},
            ]
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(config, f)
            config_path = f.name

        try:
            set_config_path(config_path)
            resp = client.post("/v1/mcp/proxy/validate-config")
            assert resp.status_code == 200
            data = resp.json()

            assert data["valid"] is True
            assert data["server_count"] == 2
            assert data["errors"] == []
            assert "new-one" in data["diff"]["to_add"]
            assert "existing" in data["diff"]["unchanged"]

            # Verify no side effects: new-one should NOT exist in the manager
            assert proxy_manager.get_server("new-one") is None
        finally:
            os.unlink(config_path)

    def test_validate_invalid_config_returns_errors(self, client: TestClient) -> None:
        """Invalid config is reported without affecting fleet."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            f.write("not json at all")
            config_path = f.name

        try:
            set_config_path(config_path)
            resp = client.post("/v1/mcp/proxy/validate-config")
            assert resp.status_code == 200
            data = resp.json()

            assert data["valid"] is False
            assert data["server_count"] == 0
            assert len(data["errors"]) > 0
            assert data["diff"] == {}
        finally:
            os.unlink(config_path)

    def test_validate_missing_file(self, client: TestClient) -> None:
        """Missing config file is reported as invalid."""
        set_config_path("/definitely/not/a/real/path.json")
        resp = client.post("/v1/mcp/proxy/validate-config")
        assert resp.status_code == 200
        data = resp.json()

        assert data["valid"] is False
        assert "not found" in data["errors"][0]

    def test_validate_no_config_path(self, client: TestClient) -> None:
        """No config path configured is reported as invalid."""
        set_config_path("")
        resp = client.post("/v1/mcp/proxy/validate-config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False


# ---------------------------------------------------------------------------
# Single-server restart diagnostics
# ---------------------------------------------------------------------------


class TestSingleServerRestartDiagnostics:
    """POST /v1/mcp/proxy/servers/{server_id}/restart -- enhanced diagnostics."""

    def test_restart_includes_duration_ms(
        self, client: TestClient, proxy_manager: ProxyManager
    ) -> None:
        """Restart response includes restart_duration_ms as a float >= 0."""
        _run(proxy_manager.add_server(_server_config("s1")))
        resp = client.post("/v1/mcp/proxy/servers/s1/restart")
        assert resp.status_code == 200
        data = resp.json()

        assert "restart_duration_ms" in data
        assert isinstance(data["restart_duration_ms"], float)
        assert data["restart_duration_ms"] >= 0

    def test_restart_includes_previous_state(
        self, client: TestClient, proxy_manager: ProxyManager
    ) -> None:
        """Restart response includes the state the server was in before restart."""
        _run(proxy_manager.add_server(_server_config("s1")))
        resp = client.post("/v1/mcp/proxy/servers/s1/restart")
        assert resp.status_code == 200
        data = resp.json()

        assert data["previous_state"] == "healthy"
        # After restart the current state should be healthy
        assert data["state"] == "healthy"

    def test_restart_preserves_existing_status_fields(
        self, client: TestClient, proxy_manager: ProxyManager
    ) -> None:
        """Restart response still includes standard status_summary fields."""
        _run(proxy_manager.add_server(_server_config("s1")))
        resp = client.post("/v1/mcp/proxy/servers/s1/restart")
        data = resp.json()

        # Standard fields from status_summary
        assert data["id"] == "s1"
        assert "state" in data
        assert "transport" in data
        assert "tool_count" in data
        assert "consecutive_failures" in data
        assert "circuit_state" in data

    def test_restart_degraded_server_captures_previous_state(
        self, client: TestClient, proxy_manager: ProxyManager
    ) -> None:
        """Restarting a DEGRADED server captures 'degraded' as previous_state."""
        _run(proxy_manager.add_server(_server_config("s1")))
        handle = proxy_manager.get_server("s1")
        assert handle is not None
        # Manually degrade the server
        handle.record_failure("test error")
        assert handle.state == ChildServerState.DEGRADED

        resp = client.post("/v1/mcp/proxy/servers/s1/restart")
        assert resp.status_code == 200
        data = resp.json()

        assert data["previous_state"] == "degraded"
        assert data["state"] == "healthy"

    def test_restart_cooldown_server_captures_previous_state(
        self, client: TestClient, proxy_manager: ProxyManager
    ) -> None:
        """Restarting a COOLDOWN server captures 'cooldown' as previous_state."""
        handle = _run(
            proxy_manager.add_server(
                ProxyServerConfig(
                    id="s1",
                    command="echo",
                    max_consecutive_failures=1,
                    cooldown_seconds=10.0,
                )
            )
        )
        # Trip the circuit breaker to enter cooldown
        handle.record_failure("boom")
        assert handle.state == ChildServerState.COOLDOWN

        resp = client.post("/v1/mcp/proxy/servers/s1/restart")
        assert resp.status_code == 200
        data = resp.json()

        assert data["previous_state"] == "cooldown"
        assert data["state"] == "healthy"


# ---------------------------------------------------------------------------
# ProxyManager unit tests for diff_config and reload_config
# ---------------------------------------------------------------------------


class TestProxyManagerDiffConfig:
    """ProxyManager.diff_config() -- pure diff computation."""

    @pytest.mark.asyncio
    async def test_diff_detects_new_servers(self) -> None:
        mgr = ProxyManager()
        await mgr.add_server(_server_config("a"))

        new_config = ProxyFleetConfig(proxy_servers=[_server_config("a"), _server_config("b")])
        diff = mgr.diff_config(new_config)

        assert diff["to_add"] == ["b"]
        assert diff["to_remove"] == []
        assert diff["unchanged"] == ["a"]

    @pytest.mark.asyncio
    async def test_diff_detects_removed_servers(self) -> None:
        mgr = ProxyManager()
        await mgr.add_server(_server_config("a"))
        await mgr.add_server(_server_config("b"))

        new_config = ProxyFleetConfig(proxy_servers=[_server_config("a")])
        diff = mgr.diff_config(new_config)

        assert diff["to_add"] == []
        assert diff["to_remove"] == ["b"]
        assert diff["unchanged"] == ["a"]

    @pytest.mark.asyncio
    async def test_diff_detects_changed_servers(self) -> None:
        mgr = ProxyManager()
        await mgr.add_server(ProxyServerConfig(id="s1", name="Old", command="echo"))

        new_config = ProxyFleetConfig(
            proxy_servers=[ProxyServerConfig(id="s1", name="New", command="node")]
        )
        diff = mgr.diff_config(new_config)

        assert diff["to_restart"] == ["s1"]
        assert diff["unchanged"] == []

    @pytest.mark.asyncio
    async def test_diff_all_unchanged(self) -> None:
        cfg = _server_config("s1")
        mgr = ProxyManager()
        await mgr.add_server(cfg)

        new_config = ProxyFleetConfig(proxy_servers=[cfg])
        diff = mgr.diff_config(new_config)

        assert diff["to_add"] == []
        assert diff["to_remove"] == []
        assert diff["to_restart"] == []
        assert diff["unchanged"] == ["s1"]

    @pytest.mark.asyncio
    async def test_diff_has_no_side_effects(self) -> None:
        """diff_config must not modify the running fleet."""
        mgr = ProxyManager()
        await mgr.add_server(_server_config("a"))

        new_config = ProxyFleetConfig(proxy_servers=[_server_config("b")])
        mgr.diff_config(new_config)

        # 'a' still exists, 'b' was not added
        assert mgr.get_server("a") is not None
        assert mgr.get_server("b") is None


class TestProxyManagerReloadConfig:
    """ProxyManager.reload_config() -- applies config diff."""

    @pytest.mark.asyncio
    async def test_reload_adds_new_servers(self) -> None:
        mgr = ProxyManager()
        await mgr.add_server(_server_config("existing"))

        new_config = ProxyFleetConfig(
            proxy_servers=[_server_config("existing"), _server_config("new")]
        )
        result = await mgr.reload_config(new_config)

        assert "new" in result["added"]
        assert mgr.get_server("new") is not None
        assert mgr.get_server("new").state == ChildServerState.HEALTHY  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_reload_removes_old_servers(self) -> None:
        mgr = ProxyManager()
        await mgr.add_server(_server_config("keep"))
        await mgr.add_server(_server_config("remove"))

        new_config = ProxyFleetConfig(proxy_servers=[_server_config("keep")])
        result = await mgr.reload_config(new_config)

        assert "remove" in result["removed"]
        assert mgr.get_server("remove") is None

    @pytest.mark.asyncio
    async def test_reload_restarts_changed_servers(self) -> None:
        mgr = ProxyManager()
        await mgr.add_server(ProxyServerConfig(id="s1", name="Old", command="echo"))

        new_config = ProxyFleetConfig(
            proxy_servers=[ProxyServerConfig(id="s1", name="New", command="node")]
        )
        result = await mgr.reload_config(new_config)

        assert "s1" in result["restarted"]
        handle = mgr.get_server("s1")
        assert handle is not None
        assert handle.config.command == "node"
        assert handle.state == ChildServerState.HEALTHY

    @pytest.mark.asyncio
    async def test_reload_leaves_unchanged_servers(self) -> None:
        cfg = _server_config("stable")
        mgr = ProxyManager()
        handle = await mgr.add_server(cfg)
        # Register a tool to verify it survives reload
        handle.register_tools([ProxyToolDefinition(name="persist_me")])

        new_config = ProxyFleetConfig(proxy_servers=[cfg])
        result = await mgr.reload_config(new_config)

        assert "stable" in result["unchanged"]
        # Verify the handle is the same object (not replaced)
        assert mgr.get_server("stable") is handle
        assert "persist_me" in handle.discovered_tools


class TestProxyManagerRestartAll:
    """ProxyManager.restart_all() -- fleet-level restart."""

    @pytest.mark.asyncio
    async def test_restart_all_returns_results(self) -> None:
        mgr = ProxyManager()
        await mgr.add_server(_server_config("a"))
        await mgr.add_server(_server_config("b"))

        result = await mgr.restart_all()

        assert sorted(result["restarted"]) == ["a", "b"]
        assert result["failed"] == []
        assert result["success_count"] == 2
        assert result["failure_count"] == 0

    @pytest.mark.asyncio
    async def test_restart_all_skips_disabled(self) -> None:
        mgr = ProxyManager()
        await mgr.add_server(_server_config("enabled"))
        await mgr.add_server(_server_config("disabled", enabled=False))

        result = await mgr.restart_all()

        assert result["restarted"] == ["enabled"]
        assert result["total"] == 1

    @pytest.mark.asyncio
    async def test_restart_all_captures_failures(self) -> None:
        mgr = ProxyManager()
        handle = await mgr.add_server(_server_config("fail"))

        async def _blow_up() -> None:
            raise RuntimeError("kaboom")

        handle.start = _blow_up  # type: ignore[method-assign]

        result = await mgr.restart_all()

        assert result["restarted"] == []
        assert len(result["failed"]) == 1
        assert result["failed"][0]["id"] == "fail"
        assert "kaboom" in result["failed"][0]["error"]
