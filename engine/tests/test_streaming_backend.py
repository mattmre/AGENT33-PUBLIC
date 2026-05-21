"""Tests for P2.5 WebSocket streaming backend transport.

These tests exercise the WebSocket streaming endpoint, authentication,
message schema validation, and the StreamingManager lifecycle using
real JWT tokens and fresh FastAPI app instances per test.
"""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import MagicMock

import jwt
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocket, WebSocketDisconnect

from agent33.api.routes.streaming import StreamEvent, StreamingManager, router
from agent33.config import settings

# ---------------------------------------------------------------------------
# Helpers -- real JWT token creation
# ---------------------------------------------------------------------------


def _make_jwt(
    sub: str = "test-user",
    scopes: list[str] | None = None,
    tenant_id: str = "t-test",
    expire_in: int = 3600,
    secret: str | None = None,
) -> str:
    """Create a real JWT token signed with the engine's configured secret."""
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": sub,
        "scopes": scopes or ["agents:invoke"],
        "iat": now,
        "exp": now + expire_in,
        "tenant_id": tenant_id,
    }
    return jwt.encode(
        payload,
        secret or settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def _make_expired_jwt() -> str:
    """Create a JWT that is already expired."""
    return _make_jwt(expire_in=-3600)


def _make_wrong_scope_jwt() -> str:
    """Create a JWT with scopes that do NOT include agents:invoke."""
    return _make_jwt(scopes=["agents:read"])


def _make_agent_definition(name: str = "test-agent") -> Any:
    """Create a minimal AgentDefinition for test fixtures."""
    from agent33.agents.definition import AgentDefinition

    return AgentDefinition(
        name=name,
        version="1.0.0",
        description="Test agent for streaming",
        role="worker",
        capabilities=["research"],
        inputs={"query": {"type": "string", "required": True}},
        outputs={"result": {"type": "string"}},
    )


# ---------------------------------------------------------------------------
# Test app factory -- fresh app per test, no global state mutation
# ---------------------------------------------------------------------------


def _create_test_app(
    *,
    streaming_manager: StreamingManager | None = None,
    agent_registry: Any = None,
    model_router: Any = None,
) -> FastAPI:
    """Create a minimal FastAPI app with the streaming router mounted."""
    app = FastAPI()
    app.include_router(router)

    if streaming_manager is not None:
        app.state.streaming_manager = streaming_manager
    if agent_registry is not None:
        app.state.agent_registry = agent_registry
    if model_router is not None:
        app.state.model_router = model_router
    return app


# ---------------------------------------------------------------------------
# StreamingManager unit tests
# ---------------------------------------------------------------------------


class TestStreamingManager:
    """Unit tests for the StreamingManager class."""

    @pytest.mark.asyncio
    async def test_connect_disconnect_lifecycle(self) -> None:
        manager = StreamingManager(max_connections=10)
        ws = MagicMock(spec=WebSocket)
        session_id = "sess-1"

        assert manager.active_count == 0

        ok = await manager.connect(ws, session_id)
        assert ok is True
        assert manager.active_count == 1

        count = await manager.session_connections(session_id)
        assert count == 1

        await manager.disconnect(ws, session_id)
        assert manager.active_count == 0

        count = await manager.session_connections(session_id)
        assert count == 0

    @pytest.mark.asyncio
    async def test_max_connections_enforced(self) -> None:
        manager = StreamingManager(max_connections=2)

        ws1 = MagicMock(spec=WebSocket)
        ws2 = MagicMock(spec=WebSocket)
        ws3 = MagicMock(spec=WebSocket)

        assert await manager.connect(ws1, "s1") is True
        assert await manager.connect(ws2, "s2") is True
        # Third connection should be rejected
        assert await manager.connect(ws3, "s3") is False
        assert manager.active_count == 2

    @pytest.mark.asyncio
    async def test_disconnect_unknown_is_noop(self) -> None:
        manager = StreamingManager(max_connections=10)
        ws = MagicMock(spec=WebSocket)
        # Should not raise
        await manager.disconnect(ws, "nonexistent-session")
        assert manager.active_count == 0

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all_session_connections(self) -> None:
        manager = StreamingManager(max_connections=10)
        ws1 = MagicMock(spec=WebSocket)
        ws2 = MagicMock(spec=WebSocket)

        # Make send_text a coroutine
        async def noop_send(text: str) -> None:
            pass

        ws1.send_text = MagicMock(side_effect=noop_send)
        ws2.send_text = MagicMock(side_effect=noop_send)

        await manager.connect(ws1, "shared-session")
        await manager.connect(ws2, "shared-session")

        event = StreamEvent(event="thinking", data={"status": "ok"}, seq=1)
        await manager.broadcast("shared-session", event)

        assert ws1.send_text.call_count == 1
        assert ws2.send_text.call_count == 1
        # Verify the payload matches the event
        sent_payload = ws1.send_text.call_args[0][0]
        parsed = json.loads(sent_payload)
        assert parsed["event"] == "thinking"
        assert parsed["seq"] == 1

    @pytest.mark.asyncio
    async def test_broadcast_removes_dead_connections(self) -> None:
        manager = StreamingManager(max_connections=10)

        ws_alive = MagicMock(spec=WebSocket)
        ws_dead = MagicMock(spec=WebSocket)

        async def noop_send(text: str) -> None:
            pass

        ws_alive.send_text = MagicMock(side_effect=noop_send)
        ws_dead.send_text = MagicMock(side_effect=RuntimeError("connection closed"))

        await manager.connect(ws_alive, "session-x")
        await manager.connect(ws_dead, "session-x")
        assert manager.active_count == 2

        event = StreamEvent(event="done", data={}, seq=99)
        await manager.broadcast("session-x", event)

        # Dead connection should have been removed
        assert manager.active_count == 1

    @pytest.mark.asyncio
    async def test_broadcast_to_empty_session_is_noop(self) -> None:
        manager = StreamingManager(max_connections=10)
        event = StreamEvent(event="done", data={}, seq=1)
        # Should not raise
        await manager.broadcast("no-such-session", event)

    @pytest.mark.asyncio
    async def test_multiple_sessions_tracked_independently(self) -> None:
        manager = StreamingManager(max_connections=10)
        ws1 = MagicMock(spec=WebSocket)
        ws2 = MagicMock(spec=WebSocket)

        await manager.connect(ws1, "session-a")
        await manager.connect(ws2, "session-b")

        assert await manager.session_connections("session-a") == 1
        assert await manager.session_connections("session-b") == 1
        assert manager.active_count == 2

        await manager.disconnect(ws1, "session-a")
        assert await manager.session_connections("session-a") == 0
        assert await manager.session_connections("session-b") == 1
        assert manager.active_count == 1


# ---------------------------------------------------------------------------
# StreamEvent model tests
# ---------------------------------------------------------------------------


class TestStreamEvent:
    """Verify StreamEvent serialization and required fields."""

    def test_event_serialization_has_required_fields(self) -> None:
        event = StreamEvent(
            event="response",
            data={"text": "hello"},
            seq=42,
        )
        payload = json.loads(event.to_json())
        assert payload["event"] == "response"
        assert payload["data"] == {"text": "hello"}
        assert payload["seq"] == 42
        assert "timestamp" in payload
        # Timestamp should be a valid ISO 8601 string
        assert "T" in payload["timestamp"]

    def test_all_event_types_serialize(self) -> None:
        for event_type in ("thinking", "tool_call", "response", "error", "done"):
            event = StreamEvent(event=event_type, data={}, seq=1)
            parsed = json.loads(event.to_json())
            assert parsed["event"] == event_type

    def test_event_data_can_contain_nested_objects(self) -> None:
        event = StreamEvent(
            event="tool_call",
            data={"tool": "shell", "args": {"cmd": "ls", "flags": ["-la"]}},
            seq=5,
        )
        parsed = json.loads(event.to_json())
        assert parsed["data"]["args"]["flags"] == ["-la"]


# ---------------------------------------------------------------------------
# WebSocket endpoint tests (with TestClient)
# ---------------------------------------------------------------------------


class TestStreamingWebSocket:
    """Integration tests for the /v1/stream/agent/{agent_id} endpoint."""

    def test_missing_credentials_closes_with_4001(self) -> None:
        """Connection without any auth token is rejected with code 4001."""
        manager = StreamingManager(max_connections=10)
        app = _create_test_app(streaming_manager=manager)
        client = TestClient(app)

        # WebSocketDisconnect.code carries the close code from the server.
        with (
            pytest.raises(WebSocketDisconnect) as exc_info,
            client.websocket_connect("/v1/stream/agent/test-agent"),
        ):
            pass
        assert exc_info.value.code == 4001

    def test_expired_token_closes_with_4001(self) -> None:
        """Connection with an expired JWT is rejected with code 4001."""
        manager = StreamingManager(max_connections=10)
        app = _create_test_app(streaming_manager=manager)
        client = TestClient(app)
        token = _make_expired_jwt()

        with (
            pytest.raises(WebSocketDisconnect) as exc_info,
            client.websocket_connect(f"/v1/stream/agent/test-agent?token={token}"),
        ):
            pass
        assert exc_info.value.code == 4001

    def test_wrong_scope_closes_with_4003(self) -> None:
        """Connection with a JWT lacking agents:invoke is rejected with 4003."""
        manager = StreamingManager(max_connections=10)
        app = _create_test_app(streaming_manager=manager)
        client = TestClient(app)
        token = _make_wrong_scope_jwt()

        with (
            pytest.raises(WebSocketDisconnect) as exc_info,
            client.websocket_connect(f"/v1/stream/agent/test-agent?token={token}"),
        ):
            pass
        assert exc_info.value.code == 4003

    def test_no_streaming_manager_closes_with_4002(self) -> None:
        """If StreamingManager is not on app.state, close with 4002."""
        app = _create_test_app(streaming_manager=None)
        client = TestClient(app)
        token = _make_jwt()

        with (
            pytest.raises(WebSocketDisconnect) as exc_info,
            client.websocket_connect(f"/v1/stream/agent/test-agent?token={token}"),
        ):
            pass
        assert exc_info.value.code == 4002

    def test_valid_token_connects_and_receives_events(self) -> None:
        """A valid JWT + well-formed input results in a full event stream."""
        manager = StreamingManager(max_connections=10)
        registry = MagicMock()
        agent_def = _make_agent_definition("my-agent")
        registry.get.return_value = agent_def
        registry.get_by_agent_id.return_value = None

        app = _create_test_app(
            streaming_manager=manager,
            agent_registry=registry,
            model_router=None,  # No model router -- triggers diagnostic path
        )
        client = TestClient(app)
        token = _make_jwt()

        with client.websocket_connect(f"/v1/stream/agent/my-agent?token={token}") as ws:
            # Send the initial input message
            ws.send_json({"input": "What is 2+2?", "context": {}})

            # Collect all events until done
            events: list[dict[str, Any]] = []
            while True:
                data = ws.receive_json()
                events.append(data)
                if data.get("event") == "done":
                    break

            # Should have at least: thinking, response, done
            event_types = [e["event"] for e in events]
            assert "thinking" in event_types
            assert "response" in event_types
            assert "done" in event_types

            # Every event must have required fields
            for event in events:
                assert "event" in event
                assert "seq" in event
                assert "timestamp" in event
                assert "data" in event
                assert isinstance(event["seq"], int)

            # Sequence numbers should be monotonically increasing
            seqs = [e["seq"] for e in events]
            assert seqs == sorted(seqs)
            assert len(set(seqs)) == len(seqs), "Sequence numbers must be unique"

            # The response event should reference the agent
            response_events = [e for e in events if e["event"] == "response"]
            assert len(response_events) == 1
            assert response_events[0]["data"]["agent"] == "my-agent"
            assert response_events[0]["data"]["input_received"] == "What is 2+2?"

    def test_query_param_token_auth_works(self) -> None:
        """Verify ?token= query parameter authentication path."""
        manager = StreamingManager(max_connections=10)
        registry = MagicMock()
        registry.get.return_value = _make_agent_definition()
        registry.get_by_agent_id.return_value = None

        app = _create_test_app(
            streaming_manager=manager,
            agent_registry=registry,
        )
        client = TestClient(app)
        token = _make_jwt()

        with client.websocket_connect(f"/v1/stream/agent/test-agent?token={token}") as ws:
            ws.send_json({"input": "Hello", "context": {}})
            events = []
            while True:
                data = ws.receive_json()
                events.append(data)
                if data.get("event") == "done":
                    break
            assert any(e["event"] == "response" for e in events)

    def test_invalid_json_input_returns_error_event(self) -> None:
        """Sending non-JSON as the first message yields an error event."""
        manager = StreamingManager(max_connections=10)
        registry = MagicMock()
        registry.get.return_value = _make_agent_definition()
        registry.get_by_agent_id.return_value = None

        app = _create_test_app(
            streaming_manager=manager,
            agent_registry=registry,
        )
        client = TestClient(app)
        token = _make_jwt()

        with client.websocket_connect(f"/v1/stream/agent/test-agent?token={token}") as ws:
            ws.send_text("not valid json{{{")
            data = ws.receive_json()
            assert data["event"] == "error"
            assert "Invalid JSON" in data["data"]["error"]

    def test_missing_input_field_returns_error_event(self) -> None:
        """Sending JSON without 'input' field yields an error event."""
        manager = StreamingManager(max_connections=10)
        registry = MagicMock()
        registry.get.return_value = _make_agent_definition()
        registry.get_by_agent_id.return_value = None

        app = _create_test_app(
            streaming_manager=manager,
            agent_registry=registry,
        )
        client = TestClient(app)
        token = _make_jwt()

        with client.websocket_connect(f"/v1/stream/agent/test-agent?token={token}") as ws:
            ws.send_json({"context": {"key": "val"}})
            data = ws.receive_json()
            assert data["event"] == "error"
            assert "input" in data["data"]["error"].lower()

    def test_empty_input_returns_error_event(self) -> None:
        """Sending empty string as input yields an error event."""
        manager = StreamingManager(max_connections=10)
        registry = MagicMock()
        registry.get.return_value = _make_agent_definition()
        registry.get_by_agent_id.return_value = None

        app = _create_test_app(
            streaming_manager=manager,
            agent_registry=registry,
        )
        client = TestClient(app)
        token = _make_jwt()

        with client.websocket_connect(f"/v1/stream/agent/test-agent?token={token}") as ws:
            ws.send_json({"input": "   ", "context": {}})
            data = ws.receive_json()
            assert data["event"] == "error"
            assert "empty" in data["data"]["error"].lower()

    def test_invalid_context_type_returns_error(self) -> None:
        """Sending a non-dict context yields an error event."""
        manager = StreamingManager(max_connections=10)
        registry = MagicMock()
        registry.get.return_value = _make_agent_definition()
        registry.get_by_agent_id.return_value = None

        app = _create_test_app(
            streaming_manager=manager,
            agent_registry=registry,
        )
        client = TestClient(app)
        token = _make_jwt()

        with client.websocket_connect(f"/v1/stream/agent/test-agent?token={token}") as ws:
            ws.send_json({"input": "hello", "context": "not-a-dict"})
            data = ws.receive_json()
            assert data["event"] == "error"
            assert "context" in data["data"]["error"].lower()

    def test_unknown_agent_returns_error_then_done(self) -> None:
        """When agent is not found, server sends error + done events."""
        manager = StreamingManager(max_connections=10)
        registry = MagicMock()
        registry.get.return_value = None
        registry.get_by_agent_id.return_value = None

        app = _create_test_app(
            streaming_manager=manager,
            agent_registry=registry,
        )
        client = TestClient(app)
        token = _make_jwt()

        with client.websocket_connect(f"/v1/stream/agent/unknown-agent?token={token}") as ws:
            ws.send_json({"input": "Hello", "context": {}})

            events = []
            while True:
                data = ws.receive_json()
                events.append(data)
                if data.get("event") == "done":
                    break

            error_events = [e for e in events if e["event"] == "error"]
            assert len(error_events) >= 1
            assert "not found" in error_events[0]["data"]["error"]

    def test_admin_scope_grants_access(self) -> None:
        """Admin scope should satisfy the agents:invoke check."""
        manager = StreamingManager(max_connections=10)
        registry = MagicMock()
        registry.get.return_value = _make_agent_definition()
        registry.get_by_agent_id.return_value = None

        app = _create_test_app(
            streaming_manager=manager,
            agent_registry=registry,
        )
        client = TestClient(app)
        token = _make_jwt(scopes=["admin"])

        with client.websocket_connect(f"/v1/stream/agent/test-agent?token={token}") as ws:
            ws.send_json({"input": "Hello admin", "context": {}})
            events = []
            while True:
                data = ws.receive_json()
                events.append(data)
                if data.get("event") == "done":
                    break
            assert any(e["event"] == "response" for e in events)

    @pytest.mark.asyncio
    async def test_max_connections_rejection_via_manager(self) -> None:
        """When max connections is reached, the manager rejects new connections.

        The Starlette TestClient is synchronous and completes each WebSocket
        lifecycle before starting the next one, so we pre-fill the manager
        with a mock connection and verify the endpoint sends an error event
        with the "Maximum connections reached" message before closing.
        """
        manager = StreamingManager(max_connections=1)

        # Pre-fill the manager with a mock connection so the limit is reached.
        mock_ws = MagicMock(spec=WebSocket)
        ok = await manager.connect(mock_ws, "pre-existing-session")
        assert ok is True
        assert manager.active_count == 1

        # Now use the endpoint -- the manager should reject the new connection.
        registry = MagicMock()
        registry.get.return_value = _make_agent_definition()
        registry.get_by_agent_id.return_value = None

        app = _create_test_app(
            streaming_manager=manager,
            agent_registry=registry,
        )
        client = TestClient(app)
        token = _make_jwt()

        # The endpoint accepts, sends an error event, then closes with 4029.
        # Since accept() already happened, the client can read the error event.
        with client.websocket_connect(f"/v1/stream/agent/test-agent?token={token}") as ws:
            data = ws.receive_json()
            assert data["event"] == "error"
            assert "Maximum connections reached" in data["data"]["error"]

    def test_done_event_has_total_events_count(self) -> None:
        """The done event should include the total event count."""
        manager = StreamingManager(max_connections=10)
        registry = MagicMock()
        registry.get.return_value = _make_agent_definition()
        registry.get_by_agent_id.return_value = None

        app = _create_test_app(
            streaming_manager=manager,
            agent_registry=registry,
        )
        client = TestClient(app)
        token = _make_jwt()

        with client.websocket_connect(f"/v1/stream/agent/test-agent?token={token}") as ws:
            ws.send_json({"input": "Count test", "context": {}})
            events = []
            while True:
                data = ws.receive_json()
                events.append(data)
                if data.get("event") == "done":
                    break

            done_event = events[-1]
            assert done_event["event"] == "done"
            assert "total_events" in done_event["data"]
            assert done_event["data"]["total_events"] == done_event["seq"]

    def test_token_signed_with_wrong_secret_rejected(self) -> None:
        """A token signed with a different secret should be rejected."""
        manager = StreamingManager(max_connections=10)
        app = _create_test_app(streaming_manager=manager)
        client = TestClient(app)

        # Sign with a completely different secret
        token = _make_jwt(secret="wrong-secret-entirely")

        with (
            pytest.raises(WebSocketDisconnect) as exc_info,
            client.websocket_connect(f"/v1/stream/agent/test-agent?token={token}"),
        ):
            pass
        assert exc_info.value.code == 4001
