"""Tests for ProxyManager aggregation, routing, and namespace deconfliction (Phase 45)."""

from __future__ import annotations

from typing import Any

import pytest

from agent33.mcp_server.proxy_child import (
    ChildServerState,
    ProxyToolDefinition,
)
from agent33.mcp_server.proxy_manager import ProxyManager
from agent33.mcp_server.proxy_models import (
    ProxyFleetConfig,
    ProxyServerConfig,
)


def _fleet_config(*servers: ProxyServerConfig) -> ProxyFleetConfig:
    return ProxyFleetConfig(proxy_servers=list(servers))


def _server_config(
    server_id: str,
    prefix: str = "",
    enabled: bool = True,
) -> ProxyServerConfig:
    return ProxyServerConfig(
        id=server_id,
        name=f"Server {server_id}",
        command="echo",
        tool_prefix=prefix,
        enabled=enabled,
    )


class TestProxyManagerFleet:
    """Fleet lifecycle: start_all, stop_all."""

    @pytest.mark.asyncio
    async def test_start_all_creates_and_starts_children(self) -> None:
        cfg = _fleet_config(
            _server_config("a", prefix="alpha"),
            _server_config("b", prefix="beta"),
        )
        mgr = ProxyManager(config=cfg)
        await mgr.start_all()
        servers = mgr.list_servers()
        assert len(servers) == 2
        assert all(s["state"] == "healthy" for s in servers)

    @pytest.mark.asyncio
    async def test_stop_all(self) -> None:
        cfg = _fleet_config(_server_config("a"))
        mgr = ProxyManager(config=cfg)
        await mgr.start_all()
        await mgr.stop_all()
        servers = mgr.list_servers()
        assert all(s["state"] == "stopped" for s in servers)

    @pytest.mark.asyncio
    async def test_disabled_server_not_started(self) -> None:
        cfg = _fleet_config(_server_config("off", enabled=False))
        mgr = ProxyManager(config=cfg)
        await mgr.start_all()
        servers = mgr.list_servers()
        assert servers[0]["state"] == "stopped"

    @pytest.mark.asyncio
    async def test_duplicate_id_skipped(self) -> None:
        cfg = _fleet_config(
            _server_config("dup"),
            _server_config("dup"),
        )
        mgr = ProxyManager(config=cfg)
        await mgr.start_all()
        assert len(mgr.list_servers()) == 1


class TestProxyManagerServerManagement:
    """add_server, remove_server, get_server."""

    @pytest.mark.asyncio
    async def test_add_server(self) -> None:
        mgr = ProxyManager()
        handle = await mgr.add_server(_server_config("new"))
        assert handle.state == ChildServerState.HEALTHY
        assert mgr.get_server("new") is handle

    @pytest.mark.asyncio
    async def test_add_duplicate_raises(self) -> None:
        mgr = ProxyManager()
        await mgr.add_server(_server_config("s1"))
        with pytest.raises(ValueError, match="already registered"):
            await mgr.add_server(_server_config("s1"))

    @pytest.mark.asyncio
    async def test_remove_server(self) -> None:
        mgr = ProxyManager()
        await mgr.add_server(_server_config("s1"))
        assert await mgr.remove_server("s1") is True
        assert mgr.get_server("s1") is None

    @pytest.mark.asyncio
    async def test_remove_nonexistent(self) -> None:
        mgr = ProxyManager()
        assert await mgr.remove_server("nope") is False


class TestProxyManagerToolAggregation:
    """Tool listing with namespace prefixes."""

    @pytest.mark.asyncio
    async def test_aggregated_tools_with_prefix(self) -> None:
        mgr = ProxyManager()
        handle = await mgr.add_server(_server_config("fs", prefix="fs"))
        handle.register_tools(
            [
                ProxyToolDefinition(name="read_file", description="Read"),
                ProxyToolDefinition(name="write_file", description="Write"),
            ]
        )
        tools = mgr.list_aggregated_tools()
        assert len(tools) == 2
        names = {t["name"] for t in tools}
        assert "fs__read_file" in names
        assert "fs__write_file" in names
        # Description should include prefix
        for t in tools:
            assert t["description"].startswith("[fs]")

    @pytest.mark.asyncio
    async def test_aggregated_tools_uses_id_when_no_prefix(self) -> None:
        mgr = ProxyManager()
        handle = await mgr.add_server(_server_config("myserver", prefix=""))
        handle.register_tools([ProxyToolDefinition(name="ping")])
        tools = mgr.list_aggregated_tools()
        assert tools[0]["name"] == "myserver__ping"

    @pytest.mark.asyncio
    async def test_stopped_servers_excluded_from_listing(self) -> None:
        mgr = ProxyManager()
        handle = await mgr.add_server(_server_config("s1", prefix="s1"))
        handle.register_tools([ProxyToolDefinition(name="tool1")])
        await handle.stop()
        tools = mgr.list_aggregated_tools()
        assert len(tools) == 0

    @pytest.mark.asyncio
    async def test_custom_separator(self) -> None:
        mgr = ProxyManager(tool_separator=".")
        handle = await mgr.add_server(_server_config("ns", prefix="ns"))
        handle.register_tools([ProxyToolDefinition(name="ping")])
        tools = mgr.list_aggregated_tools()
        assert tools[0]["name"] == "ns.ping"


class TestProxyManagerCollisionDetection:
    """Collision detection across servers and native tools."""

    @pytest.mark.asyncio
    async def test_no_collisions(self) -> None:
        mgr = ProxyManager()
        h1 = await mgr.add_server(_server_config("a", prefix="a"))
        h1.register_tools([ProxyToolDefinition(name="tool1")])
        h2 = await mgr.add_server(_server_config("b", prefix="b"))
        h2.register_tools([ProxyToolDefinition(name="tool1")])
        collisions = mgr.check_collisions()
        assert len(collisions) == 0

    @pytest.mark.asyncio
    async def test_cross_server_collision(self) -> None:
        mgr = ProxyManager()
        h1 = await mgr.add_server(_server_config("a", prefix="same"))
        h1.register_tools([ProxyToolDefinition(name="tool1")])
        h2 = await mgr.add_server(_server_config("b", prefix="same"))
        h2.register_tools([ProxyToolDefinition(name="tool1")])
        collisions = mgr.check_collisions()
        assert len(collisions) == 1
        assert "same__tool1" in collisions[0]

    @pytest.mark.asyncio
    async def test_native_tool_collision(self) -> None:
        mgr = ProxyManager()
        mgr.set_native_tool_names({"list_agents"})
        h = await mgr.add_server(_server_config("s", prefix="s"))
        # This won't collide with list_agents because it's prefixed as s__list_agents
        h.register_tools([ProxyToolDefinition(name="list_agents")])
        collisions = mgr.check_collisions()
        assert len(collisions) == 0

    @pytest.mark.asyncio
    async def test_native_tool_collision_if_same_name(self) -> None:
        mgr = ProxyManager()
        mgr.set_native_tool_names({"ns__tool1"})
        h = await mgr.add_server(_server_config("s", prefix="ns"))
        h.register_tools([ProxyToolDefinition(name="tool1")])
        collisions = mgr.check_collisions()
        assert len(collisions) == 1


class TestProxyManagerRouting:
    """Tool call routing to correct child server."""

    @pytest.mark.asyncio
    async def test_resolve_server_for_tool(self) -> None:
        mgr = ProxyManager()
        h = await mgr.add_server(_server_config("fs", prefix="fs"))
        h.register_tools([ProxyToolDefinition(name="read_file")])
        result = mgr.resolve_server_for_tool("fs__read_file")
        assert result is not None
        handle, unprefixed = result
        assert handle is h
        assert unprefixed == "read_file"

    @pytest.mark.asyncio
    async def test_resolve_unknown_tool_returns_none(self) -> None:
        mgr = ProxyManager()
        result = mgr.resolve_server_for_tool("unknown__tool")
        assert result is None

    @pytest.mark.asyncio
    async def test_call_proxy_tool_routes_correctly(self) -> None:
        mgr = ProxyManager()
        h = await mgr.add_server(_server_config("echo", prefix="echo"))
        h.register_tools([ProxyToolDefinition(name="say")])

        async def echo_handler(name: str, args: dict[str, Any]) -> dict[str, Any]:
            return {"said": args.get("text", "")}

        h._call_handler = echo_handler
        result = await mgr.call_proxy_tool("echo__say", {"text": "hello"})
        assert result["said"] == "hello"

    @pytest.mark.asyncio
    async def test_call_proxy_tool_unknown_raises(self) -> None:
        mgr = ProxyManager()
        with pytest.raises(ValueError, match="No proxy server found"):
            await mgr.call_proxy_tool("nonexistent__tool", {})


class TestProxyManagerHealthSummary:
    """Fleet health summary."""

    @pytest.mark.asyncio
    async def test_health_summary(self) -> None:
        mgr = ProxyManager()
        await mgr.add_server(_server_config("a"))
        await mgr.add_server(_server_config("b"))
        await mgr.add_server(_server_config("c", enabled=False))
        summary = mgr.health_summary()
        assert summary["total"] == 3
        assert summary["healthy"] == 2
        assert summary["stopped"] == 1
