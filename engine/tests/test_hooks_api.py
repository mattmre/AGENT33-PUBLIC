"""Tests for hook management API endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent33.api.routes.hooks import router
from agent33.hooks.models import HookDefinition, HookEventType
from agent33.hooks.protocol import BaseHook
from agent33.hooks.registry import HookRegistry

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _make_app_with_hooks(registry: HookRegistry | None = None) -> FastAPI:
    """Create a test app with hooks router and mock auth."""
    app = FastAPI()

    if registry is None:
        registry = HookRegistry()
    app.state.hook_registry = registry

    # Mock auth middleware: set request.state.user
    from starlette.middleware.base import BaseHTTPMiddleware

    class FakeAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.user = MagicMock(
                tenant_id="test-tenant",
                scopes=["admin", "hooks:read", "hooks:manage", "hooks:admin"],
            )
            return await call_next(request)

    app.add_middleware(FakeAuthMiddleware)
    app.include_router(router)
    return app


@pytest.fixture()
def registry() -> HookRegistry:
    return HookRegistry()


@pytest.fixture()
def client(registry: HookRegistry) -> TestClient:
    app = _make_app_with_hooks(registry)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestListHooks:
    def test_list_empty(self, client: TestClient) -> None:
        resp = client.get("/v1/hooks/")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_with_hooks(self, client: TestClient, registry: HookRegistry) -> None:
        hook = BaseHook(
            name="test-hook",
            event_type="agent.invoke.pre",
            priority=100,
        )
        defn = HookDefinition(
            hook_id="h1",
            name="test-hook",
            event_type=HookEventType.AGENT_INVOKE_PRE,
            handler_ref="test.Hook",
        )
        registry.register(hook, defn)

        resp = client.get("/v1/hooks/")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "test-hook"
        assert data[0]["hook_id"] == "h1"

    def test_list_filter_by_event_type(self, client: TestClient, registry: HookRegistry) -> None:
        h1 = BaseHook(name="h1", event_type="agent.invoke.pre", priority=100)
        d1 = HookDefinition(
            hook_id="d1",
            name="h1",
            event_type=HookEventType.AGENT_INVOKE_PRE,
            handler_ref="test.H",
        )
        h2 = BaseHook(name="h2", event_type="tool.execute.pre", priority=100)
        d2 = HookDefinition(
            hook_id="d2",
            name="h2",
            event_type=HookEventType.TOOL_EXECUTE_PRE,
            handler_ref="test.H",
        )
        registry.register(h1, d1)
        registry.register(h2, d2)

        resp = client.get("/v1/hooks/", params={"event_type": "agent.invoke.pre"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "h1"


class TestGetHook:
    def test_get_existing(self, client: TestClient, registry: HookRegistry) -> None:
        hook = BaseHook(name="get-me", event_type="agent.invoke.pre", priority=50)
        defn = HookDefinition(
            hook_id="get1",
            name="get-me",
            event_type=HookEventType.AGENT_INVOKE_PRE,
            handler_ref="test.H",
            priority=50,
        )
        registry.register(hook, defn)

        resp = client.get("/v1/hooks/get1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["hook_id"] == "get1"
        assert data["priority"] == 50

    def test_get_nonexistent(self, client: TestClient) -> None:
        resp = client.get("/v1/hooks/nonexistent")
        assert resp.status_code == 404


class TestUpdateHook:
    def test_update_description(self, client: TestClient, registry: HookRegistry) -> None:
        hook = BaseHook(name="upd", event_type="agent.invoke.pre", priority=100)
        defn = HookDefinition(
            hook_id="upd1",
            name="upd",
            event_type=HookEventType.AGENT_INVOKE_PRE,
            handler_ref="test.H",
        )
        registry.register(hook, defn)

        resp = client.put(
            "/v1/hooks/upd1",
            json={"description": "updated desc", "priority": 42},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["description"] == "updated desc"
        assert data["priority"] == 42

    def test_update_nonexistent(self, client: TestClient) -> None:
        resp = client.put("/v1/hooks/ghost", json={"description": "nope"})
        assert resp.status_code == 404


class TestDeleteHook:
    def test_delete_existing(self, client: TestClient, registry: HookRegistry) -> None:
        hook = BaseHook(name="del", event_type="agent.invoke.pre", priority=100)
        defn = HookDefinition(
            hook_id="del1",
            name="del",
            event_type=HookEventType.AGENT_INVOKE_PRE,
            handler_ref="test.H",
        )
        registry.register(hook, defn)

        resp = client.delete("/v1/hooks/del1")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

        # Verify it is gone
        resp2 = client.get("/v1/hooks/del1")
        assert resp2.status_code == 404

    def test_delete_nonexistent(self, client: TestClient) -> None:
        resp = client.delete("/v1/hooks/ghost")
        assert resp.status_code == 404


class TestToggleHook:
    def test_toggle_disable(self, client: TestClient, registry: HookRegistry) -> None:
        hook = BaseHook(name="tog", event_type="agent.invoke.pre", priority=100)
        defn = HookDefinition(
            hook_id="tog1",
            name="tog",
            event_type=HookEventType.AGENT_INVOKE_PRE,
            handler_ref="test.H",
        )
        registry.register(hook, defn)

        resp = client.put("/v1/hooks/tog1/toggle", json={"enabled": False})
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    def test_toggle_nonexistent(self, client: TestClient) -> None:
        resp = client.put("/v1/hooks/ghost/toggle", json={"enabled": True})
        assert resp.status_code == 404


class TestHookStats:
    def test_stats_empty(self, client: TestClient) -> None:
        resp = client.get("/v1/hooks/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_hooks"] == 0

    def test_stats_with_hooks(self, client: TestClient, registry: HookRegistry) -> None:
        h1 = BaseHook(name="s1", event_type="agent.invoke.pre", priority=100)
        h2 = BaseHook(name="s2", event_type="agent.invoke.pre", priority=200)
        registry.register(h1)
        registry.register(h2)

        resp = client.get("/v1/hooks/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_hooks"] == 2
        assert data["by_event_type"]["agent.invoke.pre"] == 2


class TestTestHook:
    def test_dry_run_existing(self, client: TestClient, registry: HookRegistry) -> None:
        hook = BaseHook(
            name="dryrun",
            event_type="agent.invoke.pre",
            priority=100,
        )
        defn = HookDefinition(
            hook_id="dry1",
            name="dryrun",
            event_type=HookEventType.AGENT_INVOKE_PRE,
            handler_ref="test.H",
        )
        registry.register(hook, defn)

        resp = client.post(
            "/v1/hooks/dry1/test",
            json={"sample_context": {"key": "val"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["hook_name"] == "dryrun"
        assert data["success"] is True

    def test_dry_run_nonexistent(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/hooks/ghost/test",
            json={"sample_context": {}},
        )
        assert resp.status_code == 404
