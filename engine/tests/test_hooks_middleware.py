"""Tests for HookMiddleware (request lifecycle hooks via Starlette)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent33.hooks.middleware import HookMiddleware
from agent33.hooks.protocol import BaseHook
from agent33.hooks.registry import HookRegistry

# ---------------------------------------------------------------------------
# Test hooks for middleware
# ---------------------------------------------------------------------------


class RequestTrackingHook(BaseHook):
    """Records that it was called with the correct context."""

    def __init__(self, event_type: str) -> None:
        super().__init__(
            name=f"tracker.{event_type}",
            event_type=event_type,
            priority=100,
            enabled=True,
            tenant_id="",
        )
        self.calls: list[dict] = []

    async def execute(self, context, call_next):
        self.calls.append(
            {
                "event_type": context.event_type,
                "method": getattr(context, "method", ""),
                "path": getattr(context, "path", ""),
                "tenant_id": context.tenant_id,
            }
        )
        return await call_next(context)


class RequestAbortHook(BaseHook):
    """Aborts pre-request hooks to block the request."""

    def __init__(self) -> None:
        super().__init__(
            name="abort_hook",
            event_type="request.pre",
            priority=10,
            enabled=True,
            tenant_id="",
        )

    async def execute(self, context, call_next):
        context.abort = True
        context.abort_reason = "blocked_by_test"
        return context


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _make_test_app(registry: HookRegistry | None = None) -> FastAPI:
    """Create a minimal FastAPI app with HookMiddleware."""
    app = FastAPI()

    if registry is not None:
        app.state.hook_registry = registry

    app.add_middleware(HookMiddleware)

    @app.get("/test")
    async def test_endpoint():
        return {"ok": True}

    @app.post("/test")
    async def post_endpoint():
        return {"posted": True}

    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHookMiddlewareNoOp:
    def test_no_registry_passthrough(self) -> None:
        """Without hook_registry on app.state, middleware is a no-op."""
        app = _make_test_app(registry=None)
        client = TestClient(app)
        resp = client.get("/test")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}


class TestHookMiddlewarePreHooks:
    def test_pre_hook_fires_on_request(self) -> None:
        registry = HookRegistry()
        pre_tracker = RequestTrackingHook("request.pre")
        registry.register(pre_tracker)

        app = _make_test_app(registry=registry)
        client = TestClient(app)
        resp = client.get("/test")
        assert resp.status_code == 200
        assert len(pre_tracker.calls) == 1
        assert pre_tracker.calls[0]["method"] == "GET"
        assert pre_tracker.calls[0]["path"] == "/test"

    def test_pre_hook_abort_returns_403(self) -> None:
        registry = HookRegistry()
        registry.register(RequestAbortHook())

        app = _make_test_app(registry=registry)
        client = TestClient(app)
        resp = client.get("/test")
        assert resp.status_code == 403
        assert "blocked_by_test" in resp.json()["detail"]


class TestHookMiddlewarePostHooks:
    def test_post_hook_fires_after_response(self) -> None:
        registry = HookRegistry()
        post_tracker = RequestTrackingHook("request.post")
        registry.register(post_tracker)

        app = _make_test_app(registry=registry)
        client = TestClient(app)
        resp = client.get("/test")
        assert resp.status_code == 200
        assert len(post_tracker.calls) == 1
        assert post_tracker.calls[0]["method"] == "GET"

    def test_post_hook_sees_correct_path(self) -> None:
        registry = HookRegistry()
        post_tracker = RequestTrackingHook("request.post")
        registry.register(post_tracker)

        app = _make_test_app(registry=registry)
        client = TestClient(app)
        client.post("/test")
        assert post_tracker.calls[0]["method"] == "POST"
        assert post_tracker.calls[0]["path"] == "/test"


class TestHookMiddlewarePreAndPost:
    def test_both_pre_and_post_fire(self) -> None:
        registry = HookRegistry()
        pre_tracker = RequestTrackingHook("request.pre")
        post_tracker = RequestTrackingHook("request.post")
        registry.register(pre_tracker)
        registry.register(post_tracker)

        app = _make_test_app(registry=registry)
        client = TestClient(app)
        resp = client.get("/test")
        assert resp.status_code == 200
        assert len(pre_tracker.calls) == 1
        assert len(post_tracker.calls) == 1

    def test_abort_prevents_post_hooks(self) -> None:
        """If pre-hook aborts, the request handler and post hooks do not fire."""
        registry = HookRegistry()
        registry.register(RequestAbortHook())
        post_tracker = RequestTrackingHook("request.post")
        registry.register(post_tracker)

        app = _make_test_app(registry=registry)
        client = TestClient(app)
        resp = client.get("/test")
        assert resp.status_code == 403
        # Post hook should NOT have been called since request was aborted
        assert len(post_tracker.calls) == 0
