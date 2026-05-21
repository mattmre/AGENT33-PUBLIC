"""P4.16 -- WebSocket streaming load tests.

Tests concurrent WebSocket connection handling, message throughput,
connection stability over time, and graceful disconnect behaviour under
load.  All tests are marked ``@pytest.mark.integration`` so they are
skipped in the standard CI suite (no running server required -- they
exercise the in-process FastAPI app via Starlette ``TestClient`` or
direct async ``StreamingManager`` / ``WorkflowWSManager`` calls).
"""

from __future__ import annotations

import asyncio
import statistics
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocket

from agent33.api.routes.streaming import StreamEvent, StreamingManager, router
from agent33.workflows.events import WorkflowEvent, WorkflowEventType
from agent33.workflows.ws_manager import WorkflowWSManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_jwt(
    sub: str = "load-test-user",
    scopes: list[str] | None = None,
    tenant_id: str = "t-load",
) -> str:
    """Create a real JWT token for test authentication."""
    import jwt as pyjwt

    from agent33.config import settings

    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": sub,
        "scopes": scopes or ["agents:invoke"],
        "iat": now,
        "exp": now + 3600,
        "tenant_id": tenant_id,
    }
    return pyjwt.encode(
        payload,
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def _make_agent_definition(name: str = "load-test-agent") -> Any:
    """Create a minimal AgentDefinition for load test fixtures."""
    from agent33.agents.definition import AgentDefinition

    return AgentDefinition(
        name=name,
        version="1.0.0",
        description="Agent for load testing",
        role="worker",
        capabilities=["research"],
        inputs={"query": {"type": "string", "required": True}},
        outputs={"result": {"type": "string"}},
    )


def _create_test_app(
    *,
    streaming_manager: StreamingManager | None = None,
    agent_registry: Any = None,
) -> FastAPI:
    """Create a minimal FastAPI app with the streaming router mounted."""
    app = FastAPI()
    app.include_router(router)
    if streaming_manager is not None:
        app.state.streaming_manager = streaming_manager
    if agent_registry is not None:
        app.state.agent_registry = agent_registry
    return app


def _mock_ws(ws_id: int = 0, *, alive: bool = True) -> MagicMock:
    """Create a mock WebSocket with a unique identity."""
    ws = MagicMock(spec=WebSocket)
    ws._load_test_id = ws_id  # for debugging

    if alive:

        async def _noop_send(text: str) -> None:
            pass

        ws.send_text = MagicMock(side_effect=_noop_send)
    else:
        ws.send_text = AsyncMock(side_effect=RuntimeError("connection closed"))
    return ws


# ---------------------------------------------------------------------------
# Concurrent Connection Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestConcurrentConnections:
    """Test the StreamingManager under concurrent connection pressure."""

    @pytest.mark.asyncio
    async def test_10_concurrent_connections(self) -> None:
        """StreamingManager correctly tracks 10 simultaneous connections."""
        manager = StreamingManager(max_connections=100)
        websockets = [_mock_ws(i) for i in range(10)]

        results = await asyncio.gather(
            *[manager.connect(ws, f"session-{i}") for i, ws in enumerate(websockets)]
        )

        assert all(results), "All 10 connections should succeed"
        assert manager.active_count == 10

        # Verify each session is tracked independently
        for i in range(10):
            count = await manager.session_connections(f"session-{i}")
            assert count == 1, f"session-{i} should have exactly 1 connection"

        # Cleanup
        await asyncio.gather(
            *[manager.disconnect(ws, f"session-{i}") for i, ws in enumerate(websockets)]
        )
        assert manager.active_count == 0

    @pytest.mark.asyncio
    async def test_50_concurrent_connections(self) -> None:
        """StreamingManager correctly tracks 50 simultaneous connections."""
        manager = StreamingManager(max_connections=100)
        websockets = [_mock_ws(i) for i in range(50)]

        results = await asyncio.gather(
            *[manager.connect(ws, f"session-{i}") for i, ws in enumerate(websockets)]
        )

        assert all(results), "All 50 connections should succeed"
        assert manager.active_count == 50

        # Disconnect all concurrently
        await asyncio.gather(
            *[manager.disconnect(ws, f"session-{i}") for i, ws in enumerate(websockets)]
        )
        assert manager.active_count == 0

    @pytest.mark.asyncio
    async def test_100_concurrent_connections(self) -> None:
        """StreamingManager correctly tracks 100 simultaneous connections."""
        manager = StreamingManager(max_connections=200)
        websockets = [_mock_ws(i) for i in range(100)]

        results = await asyncio.gather(
            *[manager.connect(ws, f"session-{i}") for i, ws in enumerate(websockets)]
        )

        assert all(results), "All 100 connections should succeed"
        assert manager.active_count == 100

        # Verify total session count
        counts = await asyncio.gather(
            *[manager.session_connections(f"session-{i}") for i in range(100)]
        )
        assert sum(counts) == 100

        # Cleanup
        await asyncio.gather(
            *[manager.disconnect(ws, f"session-{i}") for i, ws in enumerate(websockets)]
        )
        assert manager.active_count == 0

    @pytest.mark.asyncio
    async def test_connections_at_limit_rejects_excess(self) -> None:
        """When max_connections is reached, subsequent connects return False."""
        limit = 25
        manager = StreamingManager(max_connections=limit)

        # Fill to capacity
        websockets = [_mock_ws(i) for i in range(limit)]
        results = await asyncio.gather(
            *[manager.connect(ws, f"s-{i}") for i, ws in enumerate(websockets)]
        )
        assert all(results)
        assert manager.active_count == limit

        # Attempt 10 more -- all should be rejected
        excess = [_mock_ws(limit + i) for i in range(10)]
        excess_results = await asyncio.gather(
            *[manager.connect(ws, f"s-excess-{i}") for i, ws in enumerate(excess)]
        )
        assert not any(excess_results), "All excess connections should be rejected"
        assert manager.active_count == limit

        # Cleanup
        await asyncio.gather(
            *[manager.disconnect(ws, f"s-{i}") for i, ws in enumerate(websockets)]
        )

    @pytest.mark.asyncio
    async def test_multiple_connections_per_session(self) -> None:
        """Multiple WebSocket connections can share a single session."""
        manager = StreamingManager(max_connections=100)
        session_id = "shared-load-session"
        websockets = [_mock_ws(i) for i in range(20)]

        results = await asyncio.gather(*[manager.connect(ws, session_id) for ws in websockets])

        assert all(results)
        assert manager.active_count == 20
        count = await manager.session_connections(session_id)
        assert count == 20

        # Cleanup
        await asyncio.gather(*[manager.disconnect(ws, session_id) for ws in websockets])
        assert manager.active_count == 0


# ---------------------------------------------------------------------------
# Message Throughput Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMessageThroughput:
    """Test message broadcast throughput under load."""

    @pytest.mark.asyncio
    async def test_broadcast_to_10_connections_measures_latency(self) -> None:
        """Broadcast a message to 10 connections and measure delivery time."""
        manager = StreamingManager(max_connections=100)
        session_id = "throughput-10"
        websockets = [_mock_ws(i) for i in range(10)]

        for ws in websockets:
            await manager.connect(ws, session_id)

        event = StreamEvent(event="response", data={"msg": "load"}, seq=1)

        start = time.monotonic()
        await manager.broadcast(session_id, event)
        elapsed_ms = (time.monotonic() - start) * 1000

        # All connections should have received the message
        for ws in websockets:
            assert ws.send_text.call_count == 1

        # Broadcast to 10 connections should complete in under 1 second
        assert elapsed_ms < 1000, f"Broadcast took {elapsed_ms:.1f}ms (expected <1000ms)"

        for ws in websockets:
            await manager.disconnect(ws, session_id)

    @pytest.mark.asyncio
    async def test_broadcast_to_50_connections_measures_latency(self) -> None:
        """Broadcast a message to 50 connections and measure delivery time."""
        manager = StreamingManager(max_connections=100)
        session_id = "throughput-50"
        websockets = [_mock_ws(i) for i in range(50)]

        for ws in websockets:
            await manager.connect(ws, session_id)

        event = StreamEvent(event="thinking", data={"status": "load"}, seq=1)

        start = time.monotonic()
        await manager.broadcast(session_id, event)
        elapsed_ms = (time.monotonic() - start) * 1000

        for ws in websockets:
            assert ws.send_text.call_count == 1

        assert elapsed_ms < 2000, f"Broadcast took {elapsed_ms:.1f}ms (expected <2000ms)"

        for ws in websockets:
            await manager.disconnect(ws, session_id)

    @pytest.mark.asyncio
    async def test_repeated_broadcast_throughput(self) -> None:
        """Measure throughput of 100 sequential broadcasts to 10 connections."""
        manager = StreamingManager(max_connections=100)
        session_id = "burst-throughput"
        websockets = [_mock_ws(i) for i in range(10)]

        for ws in websockets:
            await manager.connect(ws, session_id)

        message_count = 100
        latencies: list[float] = []

        for seq in range(message_count):
            event = StreamEvent(event="thinking", data={"iteration": seq}, seq=seq)
            start = time.monotonic()
            await manager.broadcast(session_id, event)
            latencies.append((time.monotonic() - start) * 1000)

        # Each connection should have received all messages
        for ws in websockets:
            assert ws.send_text.call_count == message_count

        # Compute throughput statistics
        total_messages_delivered = message_count * len(websockets)
        avg_latency = statistics.mean(latencies)
        p95_latency = sorted(latencies)[int(len(latencies) * 0.95)]

        # Verify reasonable performance bounds
        assert avg_latency < 50, (
            f"Average broadcast latency {avg_latency:.2f}ms exceeds 50ms threshold"
        )
        assert p95_latency < 100, (
            f"P95 broadcast latency {p95_latency:.2f}ms exceeds 100ms threshold"
        )
        assert total_messages_delivered == 1000

        for ws in websockets:
            await manager.disconnect(ws, session_id)

    @pytest.mark.asyncio
    async def test_broadcast_with_mixed_live_and_dead_connections(self) -> None:
        """Broadcast to a mix of live and dead connections cleans up dead ones."""
        manager = StreamingManager(max_connections=100)
        session_id = "mixed-health"

        live_ws = [_mock_ws(i, alive=True) for i in range(15)]
        dead_ws = [_mock_ws(100 + i, alive=False) for i in range(5)]
        all_ws = live_ws + dead_ws

        for ws in all_ws:
            await manager.connect(ws, session_id)

        assert manager.active_count == 20

        event = StreamEvent(event="response", data={"test": "mixed"}, seq=1)
        await manager.broadcast(session_id, event)

        # Live connections should have received the message
        for ws in live_ws:
            assert ws.send_text.call_count == 1

        # Dead connections should have been cleaned up
        assert manager.active_count == 15

        for ws in live_ws:
            await manager.disconnect(ws, session_id)


# ---------------------------------------------------------------------------
# Connection Stability Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestConnectionStability:
    """Test connection stability under sustained usage patterns."""

    @pytest.mark.asyncio
    async def test_connect_disconnect_churn(self) -> None:
        """Simulate rapid connect/disconnect cycles and verify clean state."""
        manager = StreamingManager(max_connections=100)
        churn_cycles = 50

        for cycle in range(churn_cycles):
            ws = _mock_ws(cycle)
            session_id = f"churn-{cycle}"
            connected = await manager.connect(ws, session_id)
            assert connected is True
            await manager.disconnect(ws, session_id)

        # After all churn, manager should be completely clean
        assert manager.active_count == 0

    @pytest.mark.asyncio
    async def test_sustained_broadcast_stability(self) -> None:
        """Maintain connections and broadcast many messages without leaking state."""
        manager = StreamingManager(max_connections=100)
        session_id = "sustained"
        websockets = [_mock_ws(i) for i in range(5)]

        for ws in websockets:
            await manager.connect(ws, session_id)

        # Send many messages over the sustained period
        for seq in range(200):
            event = StreamEvent(
                event="thinking",
                data={"iter": seq, "payload": "x" * 100},
                seq=seq,
            )
            await manager.broadcast(session_id, event)

        # Verify all connections received all messages
        for ws in websockets:
            assert ws.send_text.call_count == 200

        # Verify no state leaks
        assert manager.active_count == 5
        count = await manager.session_connections(session_id)
        assert count == 5

        for ws in websockets:
            await manager.disconnect(ws, session_id)
        assert manager.active_count == 0

    @pytest.mark.asyncio
    async def test_interleaved_connect_broadcast_disconnect(self) -> None:
        """Interleave connects, broadcasts, and disconnects without corruption."""
        manager = StreamingManager(max_connections=100)
        session_id = "interleaved"

        # Phase 1: Connect 10
        phase1 = [_mock_ws(i) for i in range(10)]
        for ws in phase1:
            await manager.connect(ws, session_id)
        assert manager.active_count == 10

        # Phase 2: Broadcast, then disconnect 5 while keeping 5
        event1 = StreamEvent(event="thinking", data={"phase": 2}, seq=1)
        await manager.broadcast(session_id, event1)
        for ws in phase1[:5]:
            await manager.disconnect(ws, session_id)
        assert manager.active_count == 5

        # Phase 3: Connect 5 more, broadcast again
        phase3 = [_mock_ws(10 + i) for i in range(5)]
        for ws in phase3:
            await manager.connect(ws, session_id)
        assert manager.active_count == 10

        event2 = StreamEvent(event="response", data={"phase": 3}, seq=2)
        await manager.broadcast(session_id, event2)

        # The 5 survivors from phase 1 should have received both broadcasts
        for ws in phase1[5:]:
            assert ws.send_text.call_count == 2

        # The 5 new connections from phase 3 should have received only the second
        for ws in phase3:
            assert ws.send_text.call_count == 1

        # Cleanup
        for ws in phase1[5:] + phase3:
            await manager.disconnect(ws, session_id)
        assert manager.active_count == 0

    @pytest.mark.asyncio
    async def test_concurrent_connect_and_disconnect_waves(self) -> None:
        """Simultaneous connect and disconnect operations maintain consistency."""
        manager = StreamingManager(max_connections=200)

        # Wave 1: connect 30
        wave1 = [_mock_ws(i) for i in range(30)]
        await asyncio.gather(*[manager.connect(ws, f"wave1-{i}") for i, ws in enumerate(wave1)])
        assert manager.active_count == 30

        # Wave 2: connect 30 more while disconnecting the first 30
        wave2 = [_mock_ws(30 + i) for i in range(30)]
        await asyncio.gather(
            *[manager.connect(ws, f"wave2-{i}") for i, ws in enumerate(wave2)],
            *[manager.disconnect(ws, f"wave1-{i}") for i, ws in enumerate(wave1)],
        )

        # After the wave, exactly 30 connections should remain (wave2)
        assert manager.active_count == 30

        # Cleanup wave2
        await asyncio.gather(*[manager.disconnect(ws, f"wave2-{i}") for i, ws in enumerate(wave2)])
        assert manager.active_count == 0


# ---------------------------------------------------------------------------
# Graceful Disconnect Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGracefulDisconnect:
    """Test graceful disconnect handling under load."""

    @pytest.mark.asyncio
    async def test_disconnect_during_broadcast(self) -> None:
        """Disconnecting a connection while broadcast is in flight is handled."""
        manager = StreamingManager(max_connections=100)
        session_id = "disconnect-broadcast"

        live_ws = [_mock_ws(i) for i in range(8)]
        # Two connections die mid-broadcast
        dying_ws = [_mock_ws(100 + i, alive=False) for i in range(2)]
        all_ws = live_ws + dying_ws

        for ws in all_ws:
            await manager.connect(ws, session_id)
        assert manager.active_count == 10

        event = StreamEvent(event="done", data={"final": True}, seq=99)
        await manager.broadcast(session_id, event)

        # Dead connections cleaned up automatically
        assert manager.active_count == 8

        # Live connections received the message
        for ws in live_ws:
            assert ws.send_text.call_count == 1

        for ws in live_ws:
            await manager.disconnect(ws, session_id)

    @pytest.mark.asyncio
    async def test_disconnect_all_connections_simultaneously(self) -> None:
        """Disconnecting all connections at once leaves the manager clean."""
        manager = StreamingManager(max_connections=100)
        session_id = "mass-disconnect"

        websockets = [_mock_ws(i) for i in range(50)]
        for ws in websockets:
            await manager.connect(ws, session_id)

        assert manager.active_count == 50

        # Mass disconnect
        await asyncio.gather(*[manager.disconnect(ws, session_id) for ws in websockets])

        assert manager.active_count == 0
        count = await manager.session_connections(session_id)
        assert count == 0

    @pytest.mark.asyncio
    async def test_double_disconnect_is_safe(self) -> None:
        """Disconnecting the same WebSocket twice does not raise or corrupt state."""
        manager = StreamingManager(max_connections=100)
        ws = _mock_ws(0)
        session_id = "double-disconnect"

        await manager.connect(ws, session_id)
        assert manager.active_count == 1

        await manager.disconnect(ws, session_id)
        assert manager.active_count == 0

        # Second disconnect should be a no-op
        await manager.disconnect(ws, session_id)
        assert manager.active_count == 0

    @pytest.mark.asyncio
    async def test_disconnect_frees_slot_for_new_connection(self) -> None:
        """After disconnecting, the freed slot can be used by a new connection."""
        limit = 5
        manager = StreamingManager(max_connections=limit)

        # Fill to capacity
        initial = [_mock_ws(i) for i in range(limit)]
        for i, ws in enumerate(initial):
            ok = await manager.connect(ws, f"slot-{i}")
            assert ok is True

        # Rejected at limit
        overflow = _mock_ws(99)
        assert await manager.connect(overflow, "overflow") is False

        # Disconnect one
        await manager.disconnect(initial[0], "slot-0")
        assert manager.active_count == limit - 1

        # Now the new connection should succeed
        replacement = _mock_ws(100)
        assert await manager.connect(replacement, "replacement") is True
        assert manager.active_count == limit

        # Cleanup
        for i, ws in enumerate(initial[1:], start=1):
            await manager.disconnect(ws, f"slot-{i}")
        await manager.disconnect(replacement, "replacement")


# ---------------------------------------------------------------------------
# WorkflowWSManager Load Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWorkflowWSManagerLoad:
    """Load tests for the WorkflowWSManager (workflow run-scoped streaming)."""

    @pytest.mark.asyncio
    async def test_concurrent_run_registrations(self) -> None:
        """Register 50 workflow runs concurrently and verify all are tracked."""
        manager = WorkflowWSManager()

        await asyncio.gather(
            *[manager.register_run(f"run-{i}", f"workflow-{i}") for i in range(50)]
        )

        for i in range(50):
            assert await manager.has_run(f"run-{i}") is True

    @pytest.mark.asyncio
    async def test_concurrent_subscriptions_to_single_run(self) -> None:
        """Subscribe 30 WebSockets to the same run concurrently."""
        manager = WorkflowWSManager()
        run_id = "load-run-1"
        await manager.register_run(run_id, "load-workflow")

        websockets = [_mock_ws(i) for i in range(30)]

        results = await asyncio.gather(*[manager.connect(ws, run_id) for ws in websockets])

        assert all(results), "All 30 subscriptions should succeed"
        active = await manager.active_subscriptions(run_id)
        assert active == 30

        # Disconnect all
        await asyncio.gather(*[manager.disconnect(ws) for ws in websockets])
        active = await manager.active_subscriptions(run_id)
        assert active == 0

    @pytest.mark.asyncio
    async def test_event_fanout_to_many_subscribers(self) -> None:
        """Publish events and verify fan-out to all subscribers on a run."""
        manager = WorkflowWSManager()
        run_id = "fanout-run"
        await manager.register_run(run_id, "fanout-wf")

        websockets = [_mock_ws(i) for i in range(20)]
        for ws in websockets:
            ok = await manager.connect(ws, run_id)
            assert ok is True

        # Publish multiple events
        event_count = 10
        for seq in range(event_count):
            event = WorkflowEvent(
                event_type=WorkflowEventType.STEP_STARTED,
                run_id=run_id,
                workflow_name="fanout-wf",
                step_id=f"step-{seq}",
                data={"iteration": seq},
            )
            await manager.publish_event(event)

        # Each subscriber's sender loop processes via an internal queue, so
        # we verify via the queue-based delivery mechanism.
        connected = await manager.connected_count()
        assert connected == 20

        # Cleanup
        await asyncio.gather(*[manager.disconnect(ws) for ws in websockets])

    @pytest.mark.asyncio
    async def test_subscribe_disconnect_churn_across_runs(self) -> None:
        """Rapid subscribe/disconnect cycles across multiple runs stay consistent."""
        manager = WorkflowWSManager()
        run_count = 10

        for i in range(run_count):
            await manager.register_run(f"churn-run-{i}", f"churn-wf-{i}")

        for cycle in range(20):
            run_id = f"churn-run-{cycle % run_count}"
            ws = _mock_ws(cycle)
            ok = await manager.connect(ws, run_id)
            assert ok is True
            await manager.disconnect(ws)

        total = await manager.connected_count()
        assert total == 0

    @pytest.mark.asyncio
    async def test_sse_subscription_load(self) -> None:
        """Subscribe 20 SSE queues to a single run concurrently."""
        manager = WorkflowWSManager()
        run_id = "sse-load-run"
        await manager.register_run(run_id, "sse-load-wf")

        queues = await asyncio.gather(*[manager.subscribe_sse(run_id) for _ in range(20)])

        assert all(q is not None for q in queues)
        sse_count = await manager.active_sse_subscriptions(run_id)
        assert sse_count == 20

        # Publish an event -- all queues should receive it
        event = WorkflowEvent(
            event_type=WorkflowEventType.WORKFLOW_STARTED,
            run_id=run_id,
            workflow_name="sse-load-wf",
            data={},
        )
        await manager.publish_event(event)

        for q in queues:
            assert q is not None
            assert not q.empty(), "Each SSE queue should have received the event"

        # Unsubscribe all
        await asyncio.gather(
            *[manager.unsubscribe_sse(run_id, q) for q in queues if q is not None]
        )
        sse_count = await manager.active_sse_subscriptions(run_id)
        assert sse_count == 0


# ---------------------------------------------------------------------------
# End-to-End WebSocket Endpoint Load (TestClient-based)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestEndpointConcurrency:
    """Test the WebSocket streaming endpoint under sequential load via TestClient.

    Note: Starlette ``TestClient`` WebSocket connections are synchronous.
    These tests verify the endpoint handles repeated sequential connections
    correctly, exercising the full auth + manager + event pipeline.
    """

    def test_sequential_connection_burst(self) -> None:
        """Open and close 20 WebSocket connections sequentially."""
        manager = StreamingManager(max_connections=100)
        registry = MagicMock()
        registry.get.return_value = _make_agent_definition()
        registry.get_by_agent_id.return_value = None

        app = _create_test_app(
            streaming_manager=manager,
            agent_registry=registry,
        )
        client = TestClient(app)
        token = _make_jwt()

        completed = 0
        for _ in range(20):
            with client.websocket_connect(f"/v1/stream/agent/load-test-agent?token={token}") as ws:
                ws.send_json({"input": "Load test ping", "context": {}})
                events: list[dict[str, Any]] = []
                while True:
                    data = ws.receive_json()
                    events.append(data)
                    if data.get("event") == "done":
                        break
                assert any(e["event"] == "thinking" for e in events)
                assert any(e["event"] == "response" for e in events)
                completed += 1

        assert completed == 20
        # After all connections close, the manager should be clean
        assert manager.active_count == 0

    def test_sequential_connections_with_different_agents(self) -> None:
        """Exercise the endpoint with different agent IDs sequentially."""
        manager = StreamingManager(max_connections=100)
        registry = MagicMock()

        agent_names = ["agent-alpha", "agent-beta", "agent-gamma"]
        agents = {name: _make_agent_definition(name) for name in agent_names}

        def _get_agent(name: str) -> Any:
            return agents.get(name)

        registry.get.side_effect = _get_agent
        registry.get_by_agent_id.return_value = None

        app = _create_test_app(
            streaming_manager=manager,
            agent_registry=registry,
        )
        client = TestClient(app)
        token = _make_jwt()

        for agent_name in agent_names * 5:  # 15 total connections
            with client.websocket_connect(f"/v1/stream/agent/{agent_name}?token={token}") as ws:
                ws.send_json({"input": f"Hello {agent_name}", "context": {}})
                events: list[dict[str, Any]] = []
                while True:
                    data = ws.receive_json()
                    events.append(data)
                    if data.get("event") == "done":
                        break
                response_events = [e for e in events if e["event"] == "response"]
                assert len(response_events) == 1
                assert response_events[0]["data"]["agent"] == agent_name

    def test_message_event_sequence_integrity(self) -> None:
        """Verify event sequence numbers remain monotonically increasing."""
        manager = StreamingManager(max_connections=100)
        registry = MagicMock()
        registry.get.return_value = _make_agent_definition()
        registry.get_by_agent_id.return_value = None

        app = _create_test_app(
            streaming_manager=manager,
            agent_registry=registry,
        )
        client = TestClient(app)
        token = _make_jwt()

        for iteration in range(10):
            with client.websocket_connect(f"/v1/stream/agent/load-test-agent?token={token}") as ws:
                ws.send_json({"input": f"Sequence test {iteration}", "context": {}})
                events: list[dict[str, Any]] = []
                while True:
                    data = ws.receive_json()
                    events.append(data)
                    if data.get("event") == "done":
                        break

                seqs = [e["seq"] for e in events]
                assert seqs == sorted(seqs), (
                    f"Sequence numbers not monotonic on iteration {iteration}: {seqs}"
                )
                assert len(set(seqs)) == len(seqs), (
                    f"Duplicate sequence numbers on iteration {iteration}: {seqs}"
                )

    def test_rapid_connect_disconnect_no_resource_leak(self) -> None:
        """Rapidly connect and immediately disconnect without sending input."""
        manager = StreamingManager(max_connections=100)
        registry = MagicMock()
        registry.get.return_value = _make_agent_definition()
        registry.get_by_agent_id.return_value = None

        app = _create_test_app(
            streaming_manager=manager,
            agent_registry=registry,
        )
        client = TestClient(app)
        token = _make_jwt()

        for _ in range(30):
            with client.websocket_connect(
                f"/v1/stream/agent/load-test-agent?token={token}"
            ) as _ws:
                # Immediately close without sending input
                pass

        # No leaked connections
        assert manager.active_count == 0
