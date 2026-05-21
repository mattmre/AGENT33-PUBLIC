"""Tests for ChildServerHandle lifecycle, health, and tool routing (Phase 45)."""

from __future__ import annotations

from typing import Any

import pytest

from agent33.connectors.circuit_breaker import CircuitBreaker, CircuitState
from agent33.mcp_server.proxy_child import (
    ChildServerHandle,
    ChildServerState,
    ProxyToolDefinition,
)
from agent33.mcp_server.proxy_models import (
    ProxyServerConfig,
    ProxyServerGovernance,
)


def _make_handle(
    server_id: str = "test-server",
    enabled: bool = True,
    max_failures: int = 3,
    cooldown: float = 10.0,
    governance: ProxyServerGovernance | None = None,
    clock_time: float = 1000.0,
) -> ChildServerHandle:
    """Create a ChildServerHandle with injectable clock."""
    config = ProxyServerConfig(
        id=server_id,
        name=f"Test {server_id}",
        command="echo",
        enabled=enabled,
        max_consecutive_failures=max_failures,
        cooldown_seconds=cooldown,
        governance=governance or ProxyServerGovernance(),
    )
    cb = CircuitBreaker(
        failure_threshold=max_failures,
        recovery_timeout_seconds=cooldown,
        clock=lambda: clock_time,
    )
    return ChildServerHandle(config=config, circuit_breaker=cb, clock=lambda: clock_time)


class TestChildServerLifecycle:
    """Start, stop, state transitions."""

    @pytest.mark.asyncio
    async def test_start_sets_healthy(self) -> None:
        handle = _make_handle()
        assert handle.state == ChildServerState.STOPPED
        await handle.start()
        assert handle.state == ChildServerState.HEALTHY

    @pytest.mark.asyncio
    async def test_start_disabled_stays_stopped(self) -> None:
        handle = _make_handle(enabled=False)
        await handle.start()
        assert handle.state == ChildServerState.STOPPED

    @pytest.mark.asyncio
    async def test_stop_clears_tools(self) -> None:
        handle = _make_handle()
        await handle.start()
        handle.register_tools([ProxyToolDefinition(name="test_tool")])
        assert len(handle.discovered_tools) == 1
        await handle.stop()
        assert handle.state == ChildServerState.STOPPED
        assert len(handle.discovered_tools) == 0


class TestChildServerHealth:
    """Health checks, circuit breaker, cooldown."""

    @pytest.mark.asyncio
    async def test_health_check_healthy(self) -> None:
        handle = _make_handle()
        await handle.start()
        result = await handle.health_check()
        assert result is True
        assert handle.state == ChildServerState.HEALTHY

    @pytest.mark.asyncio
    async def test_health_check_stopped(self) -> None:
        handle = _make_handle()
        result = await handle.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_failure_triggers_degraded(self) -> None:
        handle = _make_handle(max_failures=3)
        await handle.start()
        handle.record_failure("error 1")
        assert handle.state == ChildServerState.DEGRADED

    @pytest.mark.asyncio
    async def test_max_failures_triggers_cooldown(self) -> None:
        handle = _make_handle(max_failures=2)
        await handle.start()
        handle.record_failure("error 1")
        handle.record_failure("error 2")
        assert handle.state == ChildServerState.COOLDOWN
        assert handle.circuit_breaker.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_success_recovers_from_degraded(self) -> None:
        handle = _make_handle(max_failures=3)
        await handle.start()
        handle.record_failure("error 1")
        assert handle.state == ChildServerState.DEGRADED
        handle.record_success()
        assert handle.state == ChildServerState.HEALTHY

    @pytest.mark.asyncio
    async def test_cooldown_recovery_via_health_check(self) -> None:
        clock_time = 1000.0
        config = ProxyServerConfig(
            id="test",
            command="echo",
            max_consecutive_failures=2,
            cooldown_seconds=10.0,
        )
        cb = CircuitBreaker(
            failure_threshold=2,
            recovery_timeout_seconds=10.0,
            clock=lambda: clock_time,
        )
        handle = ChildServerHandle(config=config, circuit_breaker=cb, clock=lambda: clock_time)
        await handle.start()
        # Trip the circuit
        handle.record_failure("err")
        handle.record_failure("err")
        assert handle.state == ChildServerState.COOLDOWN

        # Advance clock past cooldown
        clock_time = 1011.0
        handle._clock = lambda: clock_time
        handle.circuit_breaker.clock = lambda: clock_time
        result = await handle.health_check()
        assert result is True
        # Should recover
        assert handle.state in (ChildServerState.HEALTHY, ChildServerState.DEGRADED)


class TestChildServerToolDiscovery:
    """Tool registration, governance filtering."""

    def test_register_and_list_tools(self) -> None:
        handle = _make_handle()
        tools = [
            ProxyToolDefinition(name="read_file", description="Read a file"),
            ProxyToolDefinition(name="write_file", description="Write a file"),
        ]
        handle.register_tools(tools)
        listed = handle.list_tools()
        assert len(listed) == 2
        names = {t.name for t in listed}
        assert names == {"read_file", "write_file"}

    def test_blocked_tools_filtered(self) -> None:
        gov = ProxyServerGovernance(blocked_tools=["write_file"])
        handle = _make_handle(governance=gov)
        tools = [
            ProxyToolDefinition(name="read_file"),
            ProxyToolDefinition(name="write_file"),
        ]
        handle.register_tools(tools)
        listed = handle.list_tools()
        assert len(listed) == 1
        assert listed[0].name == "read_file"

    def test_allowed_tools_filter(self) -> None:
        gov = ProxyServerGovernance(allowed_tools=["read_file"])
        handle = _make_handle(governance=gov)
        tools = [
            ProxyToolDefinition(name="read_file"),
            ProxyToolDefinition(name="write_file"),
            ProxyToolDefinition(name="delete_file"),
        ]
        handle.register_tools(tools)
        listed = handle.list_tools()
        assert len(listed) == 1
        assert listed[0].name == "read_file"


class TestChildServerToolExecution:
    """Tool call routing, governance, circuit breaker enforcement."""

    @pytest.mark.asyncio
    async def test_call_tool_success(self) -> None:
        handle = _make_handle()
        await handle.start()
        handle.register_tools([ProxyToolDefinition(name="greet")])

        async def mock_handler(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
            return {"greeting": f"hello {args.get('name', 'world')}"}

        handle._call_handler = mock_handler
        result = await handle.call_tool("greet", {"name": "alice"})
        assert result["greeting"] == "hello alice"

    @pytest.mark.asyncio
    async def test_call_tool_without_handler_fails_closed(self) -> None:
        handle = _make_handle()
        await handle.start()
        handle.register_tools([ProxyToolDefinition(name="greet")])

        with pytest.raises(RuntimeError, match="no tool execution handler"):
            await handle.call_tool("greet", {"name": "alice"})
        assert handle.consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_call_tool_unknown_raises(self) -> None:
        handle = _make_handle()
        await handle.start()
        handle.register_tools([ProxyToolDefinition(name="greet")])
        with pytest.raises(ValueError, match="not found"):
            await handle.call_tool("unknown_tool", {})

    @pytest.mark.asyncio
    async def test_call_tool_deny_policy_raises(self) -> None:
        gov = ProxyServerGovernance(policy="deny")
        handle = _make_handle(governance=gov)
        await handle.start()
        handle.register_tools([ProxyToolDefinition(name="dangerous")])
        with pytest.raises(PermissionError, match="deny policy"):
            await handle.call_tool("dangerous", {})

    @pytest.mark.asyncio
    async def test_call_tool_ask_policy_requires_approval(self) -> None:
        gov = ProxyServerGovernance(policy="ask")
        handle = _make_handle(governance=gov)
        await handle.start()
        handle.register_tools([ProxyToolDefinition(name="guarded")])
        with pytest.raises(PermissionError, match="requires explicit approval"):
            await handle.call_tool("guarded", {})

    @pytest.mark.asyncio
    async def test_call_tool_blocked_raises(self) -> None:
        gov = ProxyServerGovernance(blocked_tools=["blocked_tool"])
        handle = _make_handle(governance=gov)
        await handle.start()
        handle.register_tools([ProxyToolDefinition(name="blocked_tool")])
        with pytest.raises(PermissionError, match="blocked"):
            await handle.call_tool("blocked_tool", {})

    @pytest.mark.asyncio
    async def test_call_tool_in_cooldown_raises(self) -> None:
        handle = _make_handle(max_failures=1)
        await handle.start()
        handle.register_tools([ProxyToolDefinition(name="tool_a")])
        handle.record_failure("boom")
        assert handle.state == ChildServerState.COOLDOWN
        with pytest.raises(RuntimeError, match="cooldown"):
            await handle.call_tool("tool_a", {})

    @pytest.mark.asyncio
    async def test_call_handler_failure_records_failure(self) -> None:
        handle = _make_handle()
        await handle.start()
        handle.register_tools([ProxyToolDefinition(name="flaky")])

        async def failing_handler(name: str, args: dict[str, Any]) -> Any:
            raise RuntimeError("upstream error")

        handle._call_handler = failing_handler
        with pytest.raises(RuntimeError, match="upstream error"):
            await handle.call_tool("flaky", {})
        assert handle.consecutive_failures == 1


class TestChildServerStatusSummary:
    """Status summary for API responses."""

    @pytest.mark.asyncio
    async def test_summary_structure(self) -> None:
        handle = _make_handle()
        await handle.start()
        handle.register_tools([ProxyToolDefinition(name="t1")])
        summary = handle.status_summary()
        assert summary["id"] == "test-server"
        assert summary["state"] == "healthy"
        assert summary["tool_count"] == 1
        assert summary["consecutive_failures"] == 0
        assert summary["circuit_state"] == "closed"
        assert summary["last_error"] is None
