"""Tests for Phase 32 connector monitoring UX: circuit breaker extensions,
metrics collector, API routes, and enhanced diagnostics."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from agent33.connectors.circuit_breaker import CircuitBreaker, CircuitState
from agent33.connectors.models import (
    CircuitBreakerSnapshot,
    CircuitEvent,
    ConnectorHealthSummary,
    ConnectorMetricsSummary,
    ConnectorStatus,
)
from agent33.connectors.monitoring import ConnectorMetricsCollector
from agent33.main import app
from agent33.operator.diagnostics import check_mcp
from agent33.operator.models import CheckStatus
from agent33.security.auth import create_access_token


def _auth_headers() -> dict[str, str]:
    """Return Authorization headers with a valid test token."""
    token = create_access_token("test-user", scopes=["admin"])
    return {"Authorization": f"Bearer {token}"}


# ======================================================================
# CircuitBreaker snapshot & trip tracking
# ======================================================================


class TestCircuitBreakerSnapshot:
    """Tests for the snapshot() method and trip tracking fields."""

    def test_snapshot_returns_initial_state(self) -> None:
        breaker = CircuitBreaker(failure_threshold=3)
        snap = breaker.snapshot()
        assert snap["state"] == "closed"
        assert snap["consecutive_failures"] == 0
        assert snap["total_trips"] == 0
        assert snap["last_trip_at"] is None
        assert snap["failure_threshold"] == 3
        assert snap["recovery_timeout_seconds"] == 30.0
        assert snap["half_open_success_threshold"] == 2

    def test_snapshot_after_trip(self) -> None:
        now = 100.0
        breaker = CircuitBreaker(failure_threshold=2, clock=lambda: now)
        breaker.before_call()
        breaker.record_failure()
        breaker.before_call()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        snap = breaker.snapshot()
        assert snap["state"] == "open"
        assert snap["total_trips"] == 1
        assert snap["last_trip_at"] == 100.0

    def test_snapshot_exposes_effective_and_remaining_cooldown(self) -> None:
        now = 100.0

        def _clock() -> float:
            return now

        breaker = CircuitBreaker(
            failure_threshold=1,
            recovery_timeout_seconds=10.0,
            max_recovery_timeout_seconds=80.0,
            clock=_clock,
        )

        breaker.before_call()
        breaker.record_failure()
        now = 104.0

        snap = breaker.snapshot()
        assert snap["max_recovery_timeout_seconds"] == 80.0
        assert snap["effective_recovery_timeout_seconds"] == 10.0
        assert snap["cooldown_remaining_seconds"] == pytest.approx(6.0, abs=0.01)

    def test_total_trips_increments_across_multiple_trips(self) -> None:
        now = 100.0

        def _clock() -> float:
            return now

        breaker = CircuitBreaker(
            failure_threshold=1,
            recovery_timeout_seconds=5.0,
            half_open_success_threshold=1,
            clock=_clock,
        )

        # Trip 1
        breaker.before_call()
        breaker.record_failure()
        assert breaker.total_trips == 1
        assert breaker.last_trip_at == 100.0

        # Recover
        now = 106.0
        breaker.before_call()  # transitions to HALF_OPEN
        breaker.record_success()  # transitions to CLOSED
        assert breaker.state == CircuitState.CLOSED

        # Trip 2
        now = 200.0
        breaker.before_call()
        breaker.record_failure()
        assert breaker.total_trips == 2
        assert breaker.last_trip_at == 200.0

    def test_snapshot_can_construct_pydantic_model(self) -> None:
        """The snapshot dict must be valid input for CircuitBreakerSnapshot."""
        breaker = CircuitBreaker(failure_threshold=2)
        breaker.before_call()
        breaker.record_failure()
        breaker.before_call()
        breaker.record_failure()
        snap_dict = breaker.snapshot()
        model = CircuitBreakerSnapshot(**snap_dict)
        assert model.state == "open"
        assert model.total_trips == 1


# ======================================================================
# CircuitBreaker on_state_change callback
# ======================================================================


class TestCircuitBreakerCallback:
    """Tests for the on_state_change callback."""

    def test_callback_fires_on_closed_to_open(self) -> None:
        transitions: list[tuple[str, str]] = []

        def _cb(old: CircuitState, new: CircuitState) -> None:
            transitions.append((old.value, new.value))

        breaker = CircuitBreaker(failure_threshold=1, on_state_change=_cb)
        breaker.before_call()
        breaker.record_failure()

        assert transitions == [("closed", "open")]

    def test_callback_fires_on_full_cycle(self) -> None:
        now = 100.0
        transitions: list[tuple[str, str]] = []

        def _cb(old: CircuitState, new: CircuitState) -> None:
            transitions.append((old.value, new.value))

        breaker = CircuitBreaker(
            failure_threshold=1,
            recovery_timeout_seconds=5.0,
            half_open_success_threshold=1,
            clock=lambda: now,
            on_state_change=_cb,
        )

        # CLOSED -> OPEN
        breaker.before_call()
        breaker.record_failure()

        # OPEN -> HALF_OPEN
        now = 106.0
        breaker.before_call()

        # HALF_OPEN -> CLOSED
        breaker.record_success()

        assert transitions == [
            ("closed", "open"),
            ("open", "half_open"),
            ("half_open", "closed"),
        ]

    def test_no_callback_when_state_unchanged(self) -> None:
        transitions: list[tuple[str, str]] = []

        def _cb(old: CircuitState, new: CircuitState) -> None:
            transitions.append((old.value, new.value))

        breaker = CircuitBreaker(failure_threshold=3, on_state_change=_cb)
        # Recording a success on CLOSED should not trigger a transition
        breaker.record_success()
        assert transitions == []

    def test_callback_half_open_to_open_on_failure(self) -> None:
        now = 100.0
        transitions: list[tuple[str, str]] = []

        def _cb(old: CircuitState, new: CircuitState) -> None:
            transitions.append((old.value, new.value))

        breaker = CircuitBreaker(
            failure_threshold=1,
            recovery_timeout_seconds=5.0,
            half_open_success_threshold=1,
            clock=lambda: now,
            on_state_change=_cb,
        )

        breaker.before_call()
        breaker.record_failure()

        now = 106.0
        breaker.before_call()  # -> HALF_OPEN

        breaker.record_failure()  # -> OPEN again

        assert transitions == [
            ("closed", "open"),
            ("open", "half_open"),
            ("half_open", "open"),
        ]
        assert breaker.total_trips == 2


# ======================================================================
# ConnectorMetricsCollector
# ======================================================================


class TestConnectorMetricsCollector:
    """Tests for the ConnectorMetricsCollector."""

    def test_record_call_success(self) -> None:
        collector = ConnectorMetricsCollector()
        collector.record_call("svc-a", success=True, latency_ms=12.5)
        collector.record_call("svc-a", success=True, latency_ms=8.0)
        collector.record_call("svc-a", success=False, latency_ms=50.0)

        m = collector.get_connector_metrics("svc-a")
        assert m["total_calls"] == 3
        assert m["successes"] == 2
        assert m["failures"] == 1
        assert m["success_rate"] == pytest.approx(2 / 3, abs=0.01)
        assert m["error_rate"] == pytest.approx(1 / 3, abs=0.01)
        assert m["avg_latency_ms"] > 0

    def test_get_connector_metrics_unknown_returns_zeros(self) -> None:
        collector = ConnectorMetricsCollector()
        m = collector.get_connector_metrics("nonexistent")
        assert m["total_calls"] == 0
        assert m["success_rate"] == 0.0

    def test_get_all_metrics(self) -> None:
        collector = ConnectorMetricsCollector()
        collector.record_call("svc-a", success=True, latency_ms=1.0)
        collector.record_call("svc-b", success=False, latency_ms=2.0)

        all_m = collector.get_all_metrics()
        assert "svc-a" in all_m
        assert "svc-b" in all_m
        assert all_m["svc-a"]["total_calls"] == 1
        assert all_m["svc-b"]["total_calls"] == 1

    def test_circuit_event_ring_buffer(self) -> None:
        collector = ConnectorMetricsCollector(max_events=5)
        for i in range(10):
            collector.record_circuit_event(
                "svc-a",
                old_state="closed",
                new_state=f"open-{i}",
            )
        events = collector.get_circuit_events("svc-a", limit=20)
        # Ring buffer capped at 5, newest first
        assert len(events) == 5
        assert events[0]["new_state"] == "open-9"
        assert events[4]["new_state"] == "open-5"

    def test_circuit_event_records_connector(self) -> None:
        collector = ConnectorMetricsCollector()
        collector.record_circuit_event("svc-x", "closed", "open")
        # The connector should appear in list_known_connectors
        assert "svc-x" in collector.list_known_connectors()

    def test_circuit_events_empty_for_unknown(self) -> None:
        collector = ConnectorMetricsCollector()
        assert collector.get_circuit_events("nonexistent") == []

    def test_list_known_connectors(self) -> None:
        collector = ConnectorMetricsCollector()
        collector.record_call("beta", success=True, latency_ms=1.0)
        collector.record_call("alpha", success=True, latency_ms=1.0)
        known = collector.list_known_connectors()
        assert known == ["alpha", "beta"]  # sorted

    def test_p95_latency_computed_correctly(self) -> None:
        collector = ConnectorMetricsCollector()
        # Record 100 calls with latency 1..100
        for i in range(1, 101):
            collector.record_call("svc-lat", success=True, latency_ms=float(i))
        m = collector.get_connector_metrics("svc-lat")
        # p95 should be around 95.05
        assert m["p95_latency_ms"] >= 94.0
        assert m["p95_latency_ms"] <= 96.0

    def test_metrics_summary_model_from_dict(self) -> None:
        """Verify the dict output is valid ConnectorMetricsSummary input."""
        collector = ConnectorMetricsCollector()
        collector.record_call("svc-m", success=True, latency_ms=5.0)
        raw = collector.get_connector_metrics("svc-m")
        model = ConnectorMetricsSummary(**raw)
        assert model.total_calls == 1
        assert model.successes == 1


# ======================================================================
# API routes
# ======================================================================


def _make_test_app_state() -> None:
    """Install a ConnectorMetricsCollector on the app state for route tests."""
    collector = ConnectorMetricsCollector()
    app.state.connector_metrics = collector
    return collector  # type: ignore[return-value]


class _FakeChildHandle:
    """Minimal stand-in for a ChildServerHandle for proxy route tests."""

    def __init__(
        self,
        server_id: str,
        state: str = "healthy",
        circuit_state: str = "closed",
    ) -> None:
        self.config = MagicMock()
        self.config.id = server_id
        self.config.name = f"Server {server_id}"
        self._state = state
        self.consecutive_failures = 0
        self.circuit_breaker = CircuitBreaker()
        # Override state if needed
        if circuit_state == "open":
            self.circuit_breaker.state = CircuitState.OPEN
            self.circuit_breaker.total_trips = 1
            self.circuit_breaker.last_trip_at = 100.0

    def status_summary(self) -> dict[str, Any]:
        return {
            "id": self.config.id,
            "name": self.config.name,
            "state": self._state,
            "transport": "stdio",
            "tool_count": 2,
            "uptime_seconds": 120.0,
            "consecutive_failures": self.consecutive_failures,
            "circuit_state": self.circuit_breaker.state.value,
            "last_health_check": None,
            "last_error": None,
        }

    def list_tools(self) -> list[Any]:
        return []


class _FakeProxyManager:
    """Minimal stand-in for ProxyManager."""

    def __init__(self, handles: list[_FakeChildHandle]) -> None:
        self._handles = {h.config.id: h for h in handles}

    def list_servers(self) -> list[dict[str, Any]]:
        return [h.status_summary() for h in self._handles.values()]

    def get_server(self, server_id: str) -> _FakeChildHandle | None:
        return self._handles.get(server_id)

    def health_summary(self) -> dict[str, Any]:
        total = len(self._handles)
        healthy = sum(1 for h in self._handles.values() if h._state == "healthy")
        degraded = sum(1 for h in self._handles.values() if h._state == "degraded")
        return {
            "total": total,
            "healthy": healthy,
            "degraded": degraded,
            "unhealthy": 0,
            "stopped": total - healthy - degraded,
        }


@pytest.fixture()
def _install_connector_services():
    """Install test connector services on app.state, clean up after."""
    collector = ConnectorMetricsCollector()
    app.state.connector_metrics = collector

    handles = [
        _FakeChildHandle("evokore", state="healthy"),
        _FakeChildHandle("codex", state="degraded"),
    ]
    proxy_manager = _FakeProxyManager(handles)
    app.state.proxy_manager = proxy_manager

    yield collector, proxy_manager

    # Cleanup
    if hasattr(app.state, "connector_metrics"):
        del app.state.connector_metrics
    if hasattr(app.state, "proxy_manager"):
        del app.state.proxy_manager


class TestConnectorRoutes:
    """Test the /v1/connectors API routes."""

    @pytest.mark.asyncio
    async def test_list_connectors_empty(self) -> None:
        """When no services are installed, return empty list."""
        # Ensure clean state
        for attr in ("connector_metrics", "proxy_manager"):
            if hasattr(app.state, attr):
                delattr(app.state, attr)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get("/v1/connectors")
        assert resp.status_code == 200
        data = resp.json()
        assert data["connectors"] == []
        assert data["health"]["total"] == 0

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_install_connector_services")
    async def test_list_connectors_with_proxy_servers(self) -> None:
        """When proxy servers exist, they appear in the response."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get("/v1/connectors")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["connectors"]) == 2
        ids = {c["connector_id"] for c in data["connectors"]}
        assert ids == {"evokore", "codex"}
        # Each should have a circuit snapshot
        for c in data["connectors"]:
            assert c["circuit"] is not None
            assert c["connector_type"] == "mcp_proxy"
            assert "max_recovery_timeout_seconds" in c["circuit"]
            assert "effective_recovery_timeout_seconds" in c["circuit"]
            assert "cooldown_remaining_seconds" in c["circuit"]
        # Health summary
        assert data["health"]["total"] == 2
        assert data["health"]["healthy"] == 1
        assert data["health"]["degraded"] == 1

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_install_connector_services")
    async def test_list_connectors_with_boundary_metrics(
        self,
        _install_connector_services: tuple[ConnectorMetricsCollector, Any],
    ) -> None:
        """Boundary connectors with metrics appear alongside proxy servers."""
        collector = _install_connector_services[0]
        collector.record_call("tool:web_fetch", success=True, latency_ms=15.0)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get("/v1/connectors")
        data = resp.json()
        # 2 proxy + 1 boundary
        assert len(data["connectors"]) == 3
        boundary = [c for c in data["connectors"] if c["connector_type"] == "boundary"]
        assert len(boundary) == 1
        assert boundary[0]["connector_id"] == "tool:web_fetch"
        assert boundary[0]["metrics"]["total_calls"] == 1

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_install_connector_services")
    async def test_connector_health_endpoint(self) -> None:
        """GET /v1/connectors/health returns just the summary."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get("/v1/connectors/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        # Validate it's a proper ConnectorHealthSummary shape
        ConnectorHealthSummary(**data)

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_install_connector_services")
    async def test_get_single_connector_proxy(self) -> None:
        """GET /v1/connectors/{id} returns detail for a proxy connector."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get("/v1/connectors/evokore")
        assert resp.status_code == 200
        data = resp.json()
        assert data["connector_id"] == "evokore"
        assert data["connector_type"] == "mcp_proxy"
        assert data["circuit"] is not None
        assert data["circuit"]["state"] == "closed"
        assert data["circuit"]["half_open_success_threshold"] == 2
        assert data["circuit"]["max_recovery_timeout_seconds"] == 300.0
        assert data["circuit"]["effective_recovery_timeout_seconds"] == 30.0
        assert data["circuit"]["cooldown_remaining_seconds"] == 0.0

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_install_connector_services")
    async def test_get_single_connector_boundary(
        self,
        _install_connector_services: tuple[ConnectorMetricsCollector, Any],
    ) -> None:
        """GET /v1/connectors/{id} returns detail for a boundary connector."""
        collector = _install_connector_services[0]
        collector.record_call("mcp:test", success=True, latency_ms=5.0)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get("/v1/connectors/mcp:test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["connector_id"] == "mcp:test"
        assert data["connector_type"] == "boundary"
        assert data["metrics"]["total_calls"] == 1

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_install_connector_services")
    async def test_get_single_connector_not_found(self) -> None:
        """GET /v1/connectors/{id} returns 404 for unknown connector."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get("/v1/connectors/nonexistent")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_install_connector_services")
    async def test_get_connector_events_empty(self) -> None:
        """GET /v1/connectors/{id}/events returns empty list when no events."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get("/v1/connectors/evokore/events")
        assert resp.status_code == 200
        data = resp.json()
        assert data["connector_id"] == "evokore"
        assert data["events"] == []

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_install_connector_services")
    async def test_get_connector_events_with_data(
        self,
        _install_connector_services: tuple[ConnectorMetricsCollector, Any],
    ) -> None:
        """GET /v1/connectors/{id}/events returns recorded events."""
        collector = _install_connector_services[0]
        collector.record_circuit_event("evokore", "closed", "open")
        collector.record_circuit_event("evokore", "open", "half_open")

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get("/v1/connectors/evokore/events")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 2
        # Newest first
        assert data["events"][0]["old_state"] == "open"
        assert data["events"][0]["new_state"] == "half_open"
        # Validate shape
        CircuitEvent(**data["events"][0])

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_install_connector_services")
    async def test_proxy_metrics_attached_to_proxy_connectors(
        self,
        _install_connector_services: tuple[ConnectorMetricsCollector, Any],
    ) -> None:
        """When metrics are recorded for a proxy connector ID, they appear in the listing."""
        collector = _install_connector_services[0]
        collector.record_call("evokore", success=True, latency_ms=10.0)
        collector.record_call("evokore", success=False, latency_ms=50.0)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get("/v1/connectors")
        data = resp.json()
        evokore = [c for c in data["connectors"] if c["connector_id"] == "evokore"][0]
        assert evokore["metrics"] is not None
        assert evokore["metrics"]["total_calls"] == 2
        assert evokore["metrics"]["failures"] == 1


# ======================================================================
# Enhanced DOC-14 diagnostics
# ======================================================================


class TestDoc14Diagnostics:
    """Test the enhanced DOC-14 MCP proxy diagnostic check."""

    @pytest.mark.asyncio
    async def test_doc14_no_proxy_manager(self) -> None:
        state = MagicMock(spec=[])
        result = await check_mcp(state)
        assert result.id == "DOC-14"
        assert result.status == CheckStatus.WARNING
        assert "not initialized" in result.message

    @pytest.mark.asyncio
    async def test_doc14_proxy_disabled(self) -> None:
        state = MagicMock()
        state.proxy_manager = _FakeProxyManager([])
        state.settings = MagicMock()
        state.settings.mcp_proxy_enabled = False
        result = await check_mcp(state)
        assert result.status == CheckStatus.OK
        assert "disabled" in result.message

    @pytest.mark.asyncio
    async def test_doc14_healthy_fleet(self) -> None:
        handles = [
            _FakeChildHandle("svc-a", state="healthy"),
            _FakeChildHandle("svc-b", state="healthy"),
        ]
        state = MagicMock()
        state.proxy_manager = _FakeProxyManager(handles)
        state.settings = MagicMock()
        state.settings.mcp_proxy_enabled = True
        result = await check_mcp(state)
        assert result.status == CheckStatus.OK
        assert "2 server(s)" in result.message

    @pytest.mark.asyncio
    async def test_doc14_open_circuit_triggers_warning(self) -> None:
        handles = [
            _FakeChildHandle("svc-bad", state="healthy", circuit_state="open"),
        ]
        state = MagicMock()
        state.proxy_manager = _FakeProxyManager(handles)
        state.settings = MagicMock()
        state.settings.mcp_proxy_enabled = True
        result = await check_mcp(state)
        assert result.status == CheckStatus.WARNING
        assert "circuit breaker OPEN" in result.message

    @pytest.mark.asyncio
    async def test_doc14_unhealthy_server_triggers_warning(self) -> None:
        handles = [
            _FakeChildHandle("svc-down", state="unhealthy"),
        ]
        state = MagicMock()
        state.proxy_manager = _FakeProxyManager(handles)
        state.settings = MagicMock()
        state.settings.mcp_proxy_enabled = True
        result = await check_mcp(state)
        assert result.status == CheckStatus.WARNING
        assert "UNHEALTHY" in result.message

    @pytest.mark.asyncio
    async def test_doc14_cooldown_server_triggers_warning(self) -> None:
        handles = [
            _FakeChildHandle("svc-cool", state="cooldown"),
        ]
        state = MagicMock()
        state.proxy_manager = _FakeProxyManager(handles)
        state.settings = MagicMock()
        state.settings.mcp_proxy_enabled = True
        result = await check_mcp(state)
        assert result.status == CheckStatus.WARNING
        assert "COOLDOWN" in result.message

    @pytest.mark.asyncio
    async def test_doc14_empty_fleet_ok(self) -> None:
        state = MagicMock()
        state.proxy_manager = _FakeProxyManager([])
        state.settings = MagicMock()
        state.settings.mcp_proxy_enabled = True
        result = await check_mcp(state)
        assert result.status == CheckStatus.OK
        assert "0 servers configured" in result.message


# ======================================================================
# Pydantic model validation
# ======================================================================


class TestPydanticModels:
    """Verify all new Pydantic models serialize and deserialize correctly."""

    def test_circuit_breaker_snapshot_roundtrip(self) -> None:
        snap = CircuitBreakerSnapshot(
            state="open",
            consecutive_failures=0,
            total_trips=3,
            last_trip_at=123.45,
            failure_threshold=5,
            recovery_timeout_seconds=60.0,
            half_open_success_threshold=2,
            max_recovery_timeout_seconds=300.0,
            effective_recovery_timeout_seconds=120.0,
            cooldown_remaining_seconds=45.0,
        )
        d = snap.model_dump()
        assert d["state"] == "open"
        assert d["total_trips"] == 3
        assert d["effective_recovery_timeout_seconds"] == 120.0
        rebuilt = CircuitBreakerSnapshot.model_validate(d)
        assert rebuilt == snap

    def test_connector_metrics_summary_defaults(self) -> None:
        summary = ConnectorMetricsSummary()
        assert summary.total_calls == 0
        assert summary.success_rate == 0.0

    def test_connector_status_with_optional_fields(self) -> None:
        status = ConnectorStatus(
            connector_id="test",
            name="Test Connector",
            connector_type="boundary",
            state="active",
        )
        d = status.model_dump()
        assert d["circuit"] is None
        assert d["metrics"] is None

    def test_connector_health_summary(self) -> None:
        summary = ConnectorHealthSummary(
            total=10, healthy=7, degraded=1, open_circuit=1, stopped=1
        )
        assert summary.total == 10
        d = summary.model_dump()
        assert d["open_circuit"] == 1

    def test_circuit_event_model(self) -> None:
        event = CircuitEvent(
            connector_id="svc-a",
            old_state="closed",
            new_state="open",
            timestamp=100.0,
        )
        d = event.model_dump()
        assert d["connector_id"] == "svc-a"
        assert d["timestamp"] == 100.0
