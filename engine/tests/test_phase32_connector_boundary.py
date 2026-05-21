"""Phase 32 kickoff tests: connector middleware, governance, and circuit breaker."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from agent33.connectors.boundary import get_policy_pack
from agent33.connectors.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
)
from agent33.connectors.executor import ConnectorExecutor
from agent33.connectors.governance import BlocklistConnectorPolicy
from agent33.connectors.middleware import (
    CircuitBreakerMiddleware,
    GovernanceMiddleware,
    MetricsMiddleware,
    RetryMiddleware,
    TimeoutMiddleware,
)
from agent33.connectors.models import ConnectorRequest
from agent33.tools.base import ToolContext
from agent33.tools.builtin.reader import ReaderTool
from agent33.tools.builtin.search import SearchTool
from agent33.tools.builtin.web_fetch import WebFetchTool
from agent33.tools.mcp_bridge import MCPServerConnection
from agent33.workflows.actions import http_request


class _Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _NeverCalledClient:
    async def post(self, url: str, json: dict[str, Any]) -> _Response:  # noqa: ARG002
        raise AssertionError("HTTP client should not be called when governance denies")

    async def aclose(self) -> None:
        return None


class _FailingClient:
    def __init__(self) -> None:
        self.calls = 0

    async def post(self, url: str, json: dict[str, Any]) -> _Response:  # noqa: ARG002
        self.calls += 1
        raise httpx.ConnectError("connect failed")

    async def aclose(self) -> None:
        return None


class _NeverCalledMCPSession:
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:  # noqa: ARG002
        raise AssertionError("MCP session should not be called when governance denies")


def test_policy_pack_resolution_defaults_for_unknown() -> None:
    blocked_connectors, blocked_operations = get_policy_pack("unknown-pack")
    assert blocked_connectors == frozenset()
    assert blocked_operations == frozenset()


@pytest.mark.asyncio
async def test_connector_executor_middleware_ordering() -> None:
    events: list[str] = []

    class FirstMiddleware:
        async def __call__(self, request: ConnectorRequest, call_next):
            events.append(f"first-before:{request.operation}")
            result = await call_next(request)
            events.append("first-after")
            return result

    class SecondMiddleware:
        async def __call__(self, request: ConnectorRequest, call_next):
            events.append(f"second-before:{request.operation}")
            result = await call_next(request)
            events.append("second-after")
            return result

    executor = ConnectorExecutor([FirstMiddleware(), SecondMiddleware()])
    request = ConnectorRequest(connector="mcp:test", operation="tools/list")

    async def handler(req: ConnectorRequest) -> dict[str, str]:
        events.append(f"handler:{req.operation}")
        return {"ok": "yes"}

    result = await executor.execute(request, handler)

    assert result == {"ok": "yes"}
    assert events == [
        "first-before:tools/list",
        "second-before:tools/list",
        "handler:tools/list",
        "second-after",
        "first-after",
    ]


def test_circuit_breaker_transitions_closed_open_half_open_closed() -> None:
    now = 100.0

    def _clock() -> float:
        return now

    breaker = CircuitBreaker(
        failure_threshold=2,
        recovery_timeout_seconds=10.0,
        half_open_success_threshold=1,
        clock=_clock,
    )

    breaker.before_call()
    breaker.record_failure()
    assert breaker.state == CircuitState.CLOSED

    breaker.before_call()
    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN

    with pytest.raises(CircuitOpenError):
        breaker.before_call()

    now = 111.0
    breaker.before_call()
    assert breaker.state == CircuitState.HALF_OPEN
    breaker.record_success()
    assert breaker.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_mcp_connection_boundary_governance_blocks_operation() -> None:
    executor = ConnectorExecutor(
        [
            GovernanceMiddleware(
                BlocklistConnectorPolicy(blocked_operations=frozenset({"tools/call"}))
            )
        ]
    )
    conn = MCPServerConnection(
        name="phase32",
        url="https://example.com/mcp",
        boundary_executor=executor,
    )
    conn._client = _NeverCalledClient()  # type: ignore[assignment]

    with pytest.raises(PermissionError, match="operation blocked by policy"):
        await conn.call_tool("search", {"q": "agent33"})


@pytest.mark.asyncio
async def test_mcp_connection_boundary_circuit_breaker_opens_after_failure() -> None:
    breaker = CircuitBreaker(
        failure_threshold=1,
        recovery_timeout_seconds=60.0,
        half_open_success_threshold=1,
    )
    executor = ConnectorExecutor([CircuitBreakerMiddleware(breaker)])
    conn = MCPServerConnection(
        name="phase32",
        url="https://example.com/mcp",
        boundary_executor=executor,
    )
    failing_client = _FailingClient()
    conn._client = failing_client  # type: ignore[assignment]

    with pytest.raises(httpx.ConnectError):
        await conn.list_tools()

    with pytest.raises(CircuitOpenError):
        await conn.list_tools()

    assert failing_client.calls == 1


@pytest.mark.asyncio
async def test_timeout_middleware_aborts_long_call() -> None:
    executor = ConnectorExecutor([TimeoutMiddleware(timeout_seconds=0.01)])
    request = ConnectorRequest(connector="test:timeout", operation="sleep")

    async def _handler(_request: ConnectorRequest) -> dict[str, str]:
        await asyncio.sleep(0.05)
        return {"ok": "no"}

    with pytest.raises(TimeoutError, match="connector call timed out"):
        await executor.execute(request, _handler)


@pytest.mark.asyncio
async def test_retry_middleware_retries_transient_failure() -> None:
    attempts = 0
    executor = ConnectorExecutor([RetryMiddleware(max_attempts=2)])
    request = ConnectorRequest(connector="test:retry", operation="read")

    async def _handler(_request: ConnectorRequest) -> dict[str, str]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("transient")
        return {"ok": "yes"}

    result = await executor.execute(request, _handler)
    assert result == {"ok": "yes"}
    assert attempts == 2


@pytest.mark.asyncio
async def test_metrics_middleware_records_success_metadata() -> None:
    executor = ConnectorExecutor([MetricsMiddleware()])
    request = ConnectorRequest(connector="test:metrics", operation="ping")

    async def _handler(_request: ConnectorRequest) -> dict[str, str]:
        return {"ok": "yes"}

    result = await executor.execute(request, _handler)
    assert result == {"ok": "yes"}
    metrics = request.metadata["boundary_metrics"]
    assert metrics["calls"] == 1
    assert metrics["success"] == 1
    assert metrics["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_http_request_boundary_policy_pack_blocks_web_connector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agent33.config.settings.connector_boundary_enabled", True)
    monkeypatch.setattr("agent33.config.settings.connector_policy_pack", "strict-web")

    with pytest.raises(RuntimeError, match="Connector governance blocked"):
        await http_request.execute(url="https://example.com/data", method="GET")


@pytest.mark.asyncio
async def test_mcp_policy_pack_readonly_blocks_tools_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agent33.config.settings.connector_boundary_enabled", True)
    monkeypatch.setattr("agent33.config.settings.connector_policy_pack", "mcp-readonly")

    conn = MCPServerConnection(name="readonly", url="https://example.com/mcp")
    conn._client = _NeverCalledClient()  # type: ignore[assignment]

    with pytest.raises(PermissionError, match="operation blocked by policy"):
        await conn.call_tool("search", {"q": "agent33"})


@pytest.mark.asyncio
async def test_web_fetch_boundary_policy_pack_blocks_connector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agent33.config.settings.connector_boundary_enabled", True)
    monkeypatch.setattr("agent33.config.settings.connector_policy_pack", "strict-web")
    tool = WebFetchTool()
    context = ToolContext(domain_allowlist=["example.com"])

    result = await tool.execute({"url": "https://example.com", "method": "GET"}, context)
    assert result.success is False
    assert "Connector governance blocked" in result.error


@pytest.mark.asyncio
async def test_search_boundary_policy_pack_blocks_connector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agent33.config.settings.connector_boundary_enabled", True)
    monkeypatch.setattr("agent33.config.settings.connector_policy_pack", "strict-web")

    tool = SearchTool()
    result = await tool.execute({"query": "agent33"}, ToolContext())
    assert result.success is False
    assert "Connector governance blocked" in result.error


@pytest.mark.asyncio
async def test_reader_boundary_policy_pack_blocks_connector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agent33.config.settings.connector_boundary_enabled", True)
    monkeypatch.setattr("agent33.config.settings.connector_policy_pack", "strict-web")

    tool = ReaderTool()
    context = ToolContext(domain_allowlist=["example.com"])
    result = await tool.execute({"url": "https://example.com/page"}, context)
    assert result.success is False
    assert "Connector governance blocked" in result.error


@pytest.mark.asyncio
async def test_mcp_client_manager_policy_pack_readonly_blocks_tools_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("mcp")
    from agent33.tools.mcp_client import MCPClientManager, MCPToolAdapter

    monkeypatch.setattr("agent33.config.settings.connector_boundary_enabled", True)
    monkeypatch.setattr("agent33.config.settings.connector_policy_pack", "mcp-readonly")

    manager = MCPClientManager()
    session = _NeverCalledMCPSession()
    with pytest.raises(RuntimeError, match="Connector governance blocked"):
        await manager.call_tool(session, "scan", {"target": "."})

    adapter = MCPToolAdapter(
        session=session,  # type: ignore[arg-type]
        name="scan",
        description="scan tool",
        input_schema={},
        manager=manager,
    )
    result = await adapter.execute({"target": "."}, ToolContext())
    assert result.success is False
    assert "Connector governance blocked" in result.error
