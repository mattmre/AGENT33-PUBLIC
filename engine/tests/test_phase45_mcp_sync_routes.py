"""Tests for MCP sync REST API endpoints (Phase 45)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from agent33.api.routes.mcp_sync import router


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
def client() -> TestClient:
    return TestClient(_create_test_app())


class TestPushEndpoint:
    """POST /v1/mcp/sync/push."""

    def test_push_valid_target(self, client: TestClient, tmp_path: Path) -> None:
        config_path = tmp_path / ".claude.json"
        config_path.write_text("{}", encoding="utf-8")

        with patch("agent33.mcp_server.sync._get_config_path", return_value=config_path):
            resp = client.post(
                "/v1/mcp/sync/push",
                json={"targets": ["claude_code"], "force": False},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 1
        assert data["results"][0]["status"] == "added"

    def test_push_invalid_target(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/mcp/sync/push",
            json={"targets": ["invalid_target"]},
        )
        assert resp.status_code == 400


class TestPullEndpoint:
    """POST /v1/mcp/sync/pull."""

    def test_pull_valid_target(self, client: TestClient, tmp_path: Path) -> None:
        config_path = tmp_path / ".claude.json"
        config_path.write_text(
            json.dumps({"mcpServers": {"other": {"command": "test"}}}),
            encoding="utf-8",
        )

        with patch("agent33.mcp_server.sync._get_config_path", return_value=config_path):
            resp = client.post(
                "/v1/mcp/sync/pull",
                json={"target": "claude_code"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["servers"]) == 1
        assert data["servers"][0]["name"] == "other"

    def test_pull_invalid_target(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/mcp/sync/pull",
            json={"target": "bad_target"},
        )
        assert resp.status_code == 400


class TestDiffEndpoint:
    """GET /v1/mcp/sync/diff."""

    def test_diff_returns_entries(self, client: TestClient, tmp_path: Path) -> None:
        config_path = tmp_path / ".claude.json"
        config_path.write_text("{}", encoding="utf-8")

        with patch("agent33.mcp_server.sync._get_config_path", return_value=config_path):
            resp = client.get("/v1/mcp/sync/diff")
        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data
        assert len(data["entries"]) == len(["claude_code", "claude_desktop", "cursor", "gemini"])


class TestTargetsEndpoint:
    """GET /v1/mcp/sync/targets."""

    def test_list_targets(self, client: TestClient) -> None:
        resp = client.get("/v1/mcp/sync/targets")
        assert resp.status_code == 200
        data = resp.json()
        assert "targets" in data
        assert "claude_code" in data["targets"]
