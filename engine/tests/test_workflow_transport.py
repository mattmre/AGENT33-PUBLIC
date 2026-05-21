"""Tests for S33: WebSocket-first SSE fallback transport layer."""

from __future__ import annotations

import asyncio
import contextlib
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from agent33.main import app
from agent33.security.auth import create_access_token
from agent33.workflows.events import WorkflowEvent, WorkflowEventType
from agent33.workflows.transport import (
    TransportConfig,
    TransportNegotiation,
    TransportType,
    WebSocketEventBridge,
    WorkflowTransportManager,
)
from agent33.workflows.ws_manager import WorkflowWSManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_workflow_state() -> None:
    """Reset workflow module globals and app.state between tests."""
    from agent33.api.routes import workflows

    def _reset() -> None:
        workflows.reset_workflow_state()
        if workflows._scheduler is not None:
            with contextlib.suppress(RuntimeError):
                workflows._scheduler.stop()
            workflows._scheduler = None
        workflows.set_ws_manager(None)
        app.state.ws_manager = None
        if hasattr(app.state, "workflow_transport_manager"):
            del app.state.workflow_transport_manager

    _reset()
    yield
    _reset()


@pytest.fixture
def reader_client() -> TestClient:
    token = create_access_token("transport-reader", scopes=["workflows:read"])
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def _install_transport_manager(
    manager: WorkflowTransportManager,
    ws_manager: WorkflowWSManager | None = None,
) -> None:
    from agent33.api.routes import workflows

    if ws_manager is not None:
        app.state.ws_manager = ws_manager
        workflows.set_ws_manager(ws_manager)
    app.state.workflow_transport_manager = manager


# ---------------------------------------------------------------------------
# TransportType enum
# ---------------------------------------------------------------------------


class TestTransportType:
    def test_values(self) -> None:
        assert TransportType.WEBSOCKET == "websocket"
        assert TransportType.SSE == "sse"
        assert TransportType.AUTO == "auto"

    def test_is_str_enum(self) -> None:
        assert isinstance(TransportType.WEBSOCKET, str)


# ---------------------------------------------------------------------------
# TransportConfig
# ---------------------------------------------------------------------------


class TestTransportConfig:
    def test_defaults(self) -> None:
        config = TransportConfig()
        assert config.preferred == TransportType.AUTO
        assert config.ws_ping_interval == 30.0
        assert config.ws_ping_timeout == 10.0
        assert config.sse_retry_ms == 3000
        assert config.max_reconnect_attempts == 5

    def test_custom_values(self) -> None:
        config = TransportConfig(
            preferred=TransportType.SSE,
            ws_ping_interval=15.0,
            ws_ping_timeout=5.0,
            sse_retry_ms=1000,
            max_reconnect_attempts=10,
        )
        assert config.preferred == TransportType.SSE
        assert config.ws_ping_interval == 15.0
        assert config.ws_ping_timeout == 5.0
        assert config.sse_retry_ms == 1000
        assert config.max_reconnect_attempts == 10

    def test_validation_ws_ping_interval_minimum(self) -> None:
        with pytest.raises(ValueError):
            TransportConfig(ws_ping_interval=0.5)

    def test_validation_sse_retry_ms_minimum(self) -> None:
        with pytest.raises(ValueError):
            TransportConfig(sse_retry_ms=50)


# ---------------------------------------------------------------------------
# TransportNegotiation model
# ---------------------------------------------------------------------------


class TestTransportNegotiation:
    def test_ws_negotiation(self) -> None:
        neg = TransportNegotiation(
            requested=TransportType.AUTO,
            resolved=TransportType.WEBSOCKET,
        )
        assert neg.requested == TransportType.AUTO
        assert neg.resolved == TransportType.WEBSOCKET
        assert neg.fallback_reason is None

    def test_sse_fallback(self) -> None:
        neg = TransportNegotiation(
            requested=TransportType.AUTO,
            resolved=TransportType.SSE,
            fallback_reason="No WebSocket Upgrade header present",
        )
        assert neg.resolved == TransportType.SSE
        assert neg.fallback_reason is not None

    def test_model_dump(self) -> None:
        neg = TransportNegotiation(
            requested=TransportType.WEBSOCKET,
            resolved=TransportType.WEBSOCKET,
        )
        d = neg.model_dump()
        assert d["requested"] == "websocket"
        assert d["resolved"] == "websocket"
        assert d["fallback_reason"] is None


# ---------------------------------------------------------------------------
# WorkflowTransportManager.negotiate()
# ---------------------------------------------------------------------------


class TestTransportNegotiationLogic:
    def test_negotiate_with_upgrade_header_resolves_websocket(self) -> None:
        mgr = WorkflowTransportManager()
        result = mgr.negotiate({"upgrade": "websocket"})
        assert result.resolved == TransportType.WEBSOCKET
        assert result.requested == TransportType.AUTO
        assert result.fallback_reason is None

    def test_negotiate_without_upgrade_header_resolves_sse(self) -> None:
        mgr = WorkflowTransportManager()
        result = mgr.negotiate({"accept": "text/event-stream"})
        assert result.resolved == TransportType.SSE
        assert result.requested == TransportType.AUTO
        assert result.fallback_reason == "No WebSocket Upgrade header present"

    def test_negotiate_empty_headers_resolves_sse(self) -> None:
        mgr = WorkflowTransportManager()
        result = mgr.negotiate({})
        assert result.resolved == TransportType.SSE

    def test_negotiate_preferred_sse_always_returns_sse(self) -> None:
        config = TransportConfig(preferred=TransportType.SSE)
        mgr = WorkflowTransportManager(config=config)
        result = mgr.negotiate({"upgrade": "websocket"})
        assert result.resolved == TransportType.SSE
        assert result.requested == TransportType.SSE
        assert result.fallback_reason is None

    def test_negotiate_preferred_websocket_always_returns_websocket(self) -> None:
        config = TransportConfig(preferred=TransportType.WEBSOCKET)
        mgr = WorkflowTransportManager(config=config)
        result = mgr.negotiate({})
        assert result.resolved == TransportType.WEBSOCKET
        assert result.requested == TransportType.WEBSOCKET

    def test_negotiate_case_insensitive_upgrade_header(self) -> None:
        mgr = WorkflowTransportManager()
        result = mgr.negotiate({"upgrade": "WebSocket"})
        assert result.resolved == TransportType.WEBSOCKET


# ---------------------------------------------------------------------------
# WebSocketEventBridge
# ---------------------------------------------------------------------------


class TestWebSocketEventBridge:
    async def test_subscribe_and_count(self) -> None:
        bridge = WebSocketEventBridge()
        ws = MagicMock()
        await bridge.subscribe("run-1", ws)
        assert await bridge.subscriber_count("run-1") == 1
        assert await bridge.total_subscribers() == 1
        assert await bridge.active_runs() == 1

    async def test_unsubscribe_removes_subscriber(self) -> None:
        bridge = WebSocketEventBridge()
        ws = MagicMock()
        await bridge.subscribe("run-1", ws)
        await bridge.unsubscribe("run-1", ws)
        assert await bridge.subscriber_count("run-1") == 0
        assert await bridge.active_runs() == 0

    async def test_unsubscribe_nonexistent_run_is_noop(self) -> None:
        bridge = WebSocketEventBridge()
        ws = MagicMock()
        await bridge.unsubscribe("nonexistent", ws)
        assert await bridge.total_subscribers() == 0

    async def test_multiple_subscribers_per_run(self) -> None:
        bridge = WebSocketEventBridge()
        ws1 = MagicMock()
        ws2 = MagicMock()
        ws3 = MagicMock()
        await bridge.subscribe("run-1", ws1)
        await bridge.subscribe("run-1", ws2)
        await bridge.subscribe("run-1", ws3)
        assert await bridge.subscriber_count("run-1") == 3
        assert await bridge.total_subscribers() == 3

    async def test_multiple_runs(self) -> None:
        bridge = WebSocketEventBridge()
        ws1 = MagicMock()
        ws2 = MagicMock()
        await bridge.subscribe("run-1", ws1)
        await bridge.subscribe("run-2", ws2)
        assert await bridge.active_runs() == 2
        assert await bridge.total_subscribers() == 2

    async def test_broadcast_sends_to_all_subscribers(self) -> None:
        bridge = WebSocketEventBridge()
        ws1 = MagicMock()
        ws1.send_text = AsyncMock()
        ws2 = MagicMock()
        ws2.send_text = AsyncMock()
        await bridge.subscribe("run-1", ws1)
        await bridge.subscribe("run-1", ws2)

        event = {"type": "step_started", "run_id": "run-1"}
        await bridge.broadcast("run-1", event)

        expected_payload = json.dumps(event)
        ws1.send_text.assert_called_once_with(expected_payload)
        ws2.send_text.assert_called_once_with(expected_payload)

    async def test_broadcast_does_not_send_to_other_runs(self) -> None:
        bridge = WebSocketEventBridge()
        ws1 = MagicMock()
        ws1.send_text = AsyncMock()
        ws2 = MagicMock()
        ws2.send_text = AsyncMock()
        await bridge.subscribe("run-1", ws1)
        await bridge.subscribe("run-2", ws2)

        await bridge.broadcast("run-1", {"type": "test"})

        ws1.send_text.assert_called_once()
        ws2.send_text.assert_not_called()

    async def test_broadcast_to_empty_run_is_noop(self) -> None:
        bridge = WebSocketEventBridge()
        await bridge.broadcast("nonexistent", {"type": "test"})

    async def test_broadcast_removes_dead_connections(self) -> None:
        bridge = WebSocketEventBridge()
        ws_alive = MagicMock()
        ws_alive.send_text = AsyncMock()
        ws_dead = MagicMock()
        ws_dead.send_text = AsyncMock(side_effect=RuntimeError("connection closed"))

        await bridge.subscribe("run-1", ws_alive)
        await bridge.subscribe("run-1", ws_dead)

        await bridge.broadcast("run-1", {"type": "test"})

        # Dead connection should be cleaned up
        assert await bridge.subscriber_count("run-1") == 1

    async def test_cleanup_on_all_dead(self) -> None:
        bridge = WebSocketEventBridge()
        ws_dead = MagicMock()
        ws_dead.send_text = AsyncMock(side_effect=RuntimeError("closed"))

        await bridge.subscribe("run-1", ws_dead)
        await bridge.broadcast("run-1", {"type": "test"})

        assert await bridge.subscriber_count("run-1") == 0
        assert await bridge.active_runs() == 0


# ---------------------------------------------------------------------------
# WorkflowTransportManager: create_ws_handler
# ---------------------------------------------------------------------------


class TestCreateWsHandler:
    async def test_creates_callable(self) -> None:
        mgr = WorkflowTransportManager()
        handler = mgr.create_ws_handler("run-1")
        assert callable(handler)

    async def test_handler_subscribes_and_unsubscribes(self) -> None:
        mgr = WorkflowTransportManager()
        handler = mgr.create_ws_handler("run-1")

        ws = MagicMock()
        # Make receive_text raise after first call to simulate disconnect
        ws.receive_text = AsyncMock(side_effect=RuntimeError("disconnected"))

        await handler(ws)

        # After handler completes, the WS should be unsubscribed
        assert await mgr.bridge.subscriber_count("run-1") == 0

    async def test_handler_increments_stats(self) -> None:
        mgr = WorkflowTransportManager()
        handler = mgr.create_ws_handler("run-1")

        ws = MagicMock()
        ws.receive_text = AsyncMock(side_effect=RuntimeError("disconnected"))
        await handler(ws)

        stats = await mgr.get_transport_stats()
        assert stats["total_ws_served"] == 1


# ---------------------------------------------------------------------------
# WorkflowTransportManager: get_transport_stats
# ---------------------------------------------------------------------------


class TestTransportStats:
    async def test_initial_stats(self) -> None:
        mgr = WorkflowTransportManager()
        stats = await mgr.get_transport_stats()

        assert stats["active_ws_connections"] == 0
        assert stats["active_ws_bridge_subscribers"] == 0
        assert stats["active_ws_bridge_runs"] == 0
        assert stats["active_ws_manager_connections"] == 0
        assert stats["active_sse_streams"] == 0
        assert stats["total_ws_served"] == 0
        assert stats["total_sse_served"] == 0
        assert stats["total_served"] == 0
        assert stats["transport_preferred"] == "auto"
        assert "config" in stats
        assert stats["uptime_seconds"] >= 0.0

    async def test_stats_with_ws_manager(self) -> None:
        ws_manager = WorkflowWSManager()
        mgr = WorkflowTransportManager(ws_manager=ws_manager)
        stats = await mgr.get_transport_stats()
        assert stats["active_ws_manager_connections"] == 0

    async def test_stats_config_reflects_transport_config(self) -> None:
        config = TransportConfig(
            preferred=TransportType.SSE,
            ws_ping_interval=15.0,
            sse_retry_ms=5000,
        )
        mgr = WorkflowTransportManager(config=config)
        stats = await mgr.get_transport_stats()
        assert stats["config"]["preferred"] == "sse"
        assert stats["config"]["ws_ping_interval"] == 15.0
        assert stats["config"]["sse_retry_ms"] == 5000


# ---------------------------------------------------------------------------
# WorkflowTransportManager: create_sse_handler
# ---------------------------------------------------------------------------


class TestCreateSseHandler:
    async def test_sse_handler_without_ws_manager_returns_immediately(self) -> None:
        mgr = WorkflowTransportManager(ws_manager=None)
        gen = mgr.create_sse_handler("run-1")
        events: list[str] = []
        async for frame in gen:
            events.append(frame)
        assert events == []

    async def test_sse_handler_with_ws_manager_replays_and_streams(self) -> None:
        ws_manager = WorkflowWSManager()
        await ws_manager.register_run("run-1", "test-workflow")

        # Publish an event so it appears in the replay buffer
        event = WorkflowEvent(
            event_type=WorkflowEventType.WORKFLOW_STARTED,
            run_id="run-1",
            workflow_name="test-workflow",
        )
        await ws_manager.publish_event(event)

        mgr = WorkflowTransportManager(ws_manager=ws_manager)
        gen = mgr.create_sse_handler("run-1", last_event_id="0")

        # Collect the first frame (should be the replayed event)
        frames: list[str] = []

        async def _collect() -> None:
            async for frame in gen:
                frames.append(frame)
                break  # Stop after the first replayed event

        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(_collect(), timeout=2.0)

        assert len(frames) >= 1
        assert "data:" in frames[0]

    async def test_sse_handler_increments_stats(self) -> None:
        ws_manager = WorkflowWSManager()
        await ws_manager.register_run("run-1", "test-workflow")

        mgr = WorkflowTransportManager(ws_manager=ws_manager)
        gen = mgr.create_sse_handler("run-1")

        async def _drain() -> None:
            async for _ in gen:
                break

        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(_drain(), timeout=0.5)

        stats = await mgr.get_transport_stats()
        assert stats["total_sse_served"] == 1

    async def test_sse_handler_unknown_run_returns_empty(self) -> None:
        ws_manager = WorkflowWSManager()
        mgr = WorkflowTransportManager(ws_manager=ws_manager)

        gen = mgr.create_sse_handler("nonexistent")
        frames: list[str] = []
        async for frame in gen:
            frames.append(frame)
        assert frames == []


# ---------------------------------------------------------------------------
# Settings config field validation
# ---------------------------------------------------------------------------


class TestConfigSettings:
    def test_workflow_transport_preferred_default(self) -> None:
        from agent33.config import Settings

        s = Settings()
        assert s.workflow_transport_preferred == "auto"

    def test_workflow_transport_preferred_valid_values(self) -> None:
        from agent33.config import Settings

        for value in ("auto", "websocket", "sse", "AUTO", "WebSocket", "SSE"):
            s = Settings(workflow_transport_preferred=value)
            assert s.workflow_transport_preferred == value.strip().lower()

    def test_workflow_transport_preferred_invalid(self) -> None:
        from agent33.config import Settings

        with pytest.raises(ValueError):
            Settings(workflow_transport_preferred="grpc")

    def test_workflow_ws_ping_interval_default(self) -> None:
        from agent33.config import Settings

        s = Settings()
        assert s.workflow_ws_ping_interval == 30.0

    def test_workflow_ws_ping_timeout_default(self) -> None:
        from agent33.config import Settings

        s = Settings()
        assert s.workflow_ws_ping_timeout == 10.0


# ---------------------------------------------------------------------------
# API route tests
# ---------------------------------------------------------------------------


class TestTransportConfigRoute:
    def test_returns_config_without_manager(self, reader_client: TestClient) -> None:
        resp = reader_client.get("/v1/workflows/transport/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["preferred"] == "auto"
        assert data["ws_ping_interval"] == 30.0
        assert data["ws_ping_timeout"] == 10.0
        assert data["sse_retry_ms"] == 3000
        assert data["max_reconnect_attempts"] == 5

    def test_returns_config_with_manager(self, reader_client: TestClient) -> None:
        config = TransportConfig(
            preferred=TransportType.WEBSOCKET,
            ws_ping_interval=20.0,
            ws_ping_timeout=8.0,
            sse_retry_ms=2000,
            max_reconnect_attempts=3,
        )
        mgr = WorkflowTransportManager(config=config)
        _install_transport_manager(mgr)

        resp = reader_client.get("/v1/workflows/transport/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["preferred"] == "websocket"
        assert data["ws_ping_interval"] == 20.0
        assert data["ws_ping_timeout"] == 8.0
        assert data["sse_retry_ms"] == 2000
        assert data["max_reconnect_attempts"] == 3

    def test_requires_auth(self) -> None:
        client = TestClient(app)
        resp = client.get("/v1/workflows/transport/config")
        assert resp.status_code == 401


class TestTransportStatsRoute:
    def test_returns_stats_without_manager(self, reader_client: TestClient) -> None:
        resp = reader_client.get("/v1/workflows/transport/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_ws_connections"] == 0
        assert data["total_served"] == 0
        assert data["transport_preferred"] == "auto"

    def test_returns_stats_with_manager(self, reader_client: TestClient) -> None:
        ws_manager = WorkflowWSManager()
        config = TransportConfig(preferred=TransportType.SSE)
        mgr = WorkflowTransportManager(config=config, ws_manager=ws_manager)
        _install_transport_manager(mgr, ws_manager=ws_manager)

        resp = reader_client.get("/v1/workflows/transport/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["transport_preferred"] == "sse"
        assert data["active_ws_connections"] == 0
        assert "config" in data
        assert data["uptime_seconds"] >= 0.0

    def test_requires_auth(self) -> None:
        client = TestClient(app)
        resp = client.get("/v1/workflows/transport/stats")
        assert resp.status_code == 401


class TestTransportNegotiateRoute:
    def test_negotiate_without_manager(self, reader_client: TestClient) -> None:
        resp = reader_client.get("/v1/workflows/transport/negotiate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["resolved"] == "sse"
        assert "Transport manager not initialized" in data["fallback_reason"]

    def test_negotiate_with_manager(self, reader_client: TestClient) -> None:
        mgr = WorkflowTransportManager()
        _install_transport_manager(mgr)

        resp = reader_client.get("/v1/workflows/transport/negotiate")
        assert resp.status_code == 200
        data = resp.json()
        # HTTP GET does not have an Upgrade header, so SSE is expected
        assert data["resolved"] == "sse"
        assert data["requested"] == "auto"

    def test_requires_auth(self) -> None:
        client = TestClient(app)
        resp = client.get("/v1/workflows/transport/negotiate")
        assert resp.status_code == 401
