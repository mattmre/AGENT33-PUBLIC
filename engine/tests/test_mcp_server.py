"""Tests for MCP route wiring and server integration."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent33.api.routes.mcp import router
from agent33.mcp_server.proxy_child import ChildServerHandle, ChildServerState, ProxyToolDefinition
from agent33.mcp_server.proxy_manager import ProxyManager
from agent33.mcp_server.proxy_models import ProxyServerConfig
from agent33.security.auth import create_access_token
from agent33.security.middleware import AuthMiddleware


def _make_headers(*scopes: str) -> dict[str, str]:
    token = create_access_token("test-user", scopes=list(scopes))
    return {"Authorization": f"Bearer {token}"}


def _build_route_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(router)
    app.state.mcp_bridge = MagicMock()
    app.state.mcp_bridge.get_system_status.return_value = {
        "status": "operational",
        "agents_loaded": 1,
    }
    app.state.mcp_server = None
    app.state.mcp_transport = None
    return app


class _FakeSseContext:
    async def __aenter__(self) -> tuple[str, str]:
        return ("read-stream", "write-stream")

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
        return False


class _FakeTransport:
    def __init__(self) -> None:
        self.connect_calls: list[tuple[object, object, object]] = []
        self.message_calls: list[tuple[object, object, object, bytes]] = []

    def connect_sse(self, scope, receive, send):  # type: ignore[no-untyped-def]
        self.connect_calls.append((scope, receive, send))
        return _FakeSseContext()

    async def handle_post_message(self, scope, receive, send, body):  # type: ignore[no-untyped-def]
        self.message_calls.append((scope, receive, send, body))


class _FakeMCPServer:
    def __init__(self) -> None:
        self.run = AsyncMock()

    def create_initialization_options(self) -> dict[str, str]:
        return {"mode": "test"}


class _RecordingServer:
    def __init__(self, request: object | None = None) -> None:
        self.request_context = SimpleNamespace(request=request)
        self.handlers: dict[str, object] = {}

    def list_tools(self):
        def decorator(fn):
            self.handlers["list_tools"] = fn
            return fn

        return decorator

    def call_tool(self):
        def decorator(fn):
            self.handlers["call_tool"] = fn
            return fn

        return decorator

    def list_resources(self):
        def decorator(fn):
            self.handlers["list_resources"] = fn
            return fn

        return decorator

    def list_resource_templates(self):
        def decorator(fn):
            self.handlers["list_resource_templates"] = fn
            return fn

        return decorator

    def read_resource(self):
        def decorator(fn):
            self.handlers["read_resource"] = fn
            return fn

        return decorator


class _ToolDescriptor(SimpleNamespace):
    pass


class _TextContent(SimpleNamespace):
    pass


class TestMCPRoutes:
    def test_sse_and_messages_require_authentication(self) -> None:
        app = _build_route_app()
        client = TestClient(app)

        assert client.get("/v1/mcp/sse").status_code == 401
        assert client.post("/v1/mcp/messages", content=b"{}").status_code == 401

    def test_status_requires_agents_read_scope(self) -> None:
        app = _build_route_app()
        client = TestClient(app)

        forbidden = client.get("/v1/mcp/status", headers=_make_headers("workflows:read"))
        assert forbidden.status_code == 403

        allowed = client.get("/v1/mcp/status", headers=_make_headers("agents:read"))
        assert allowed.status_code == 200
        assert allowed.json()["status"] == "operational"
        assert allowed.json()["available"] is False
        assert allowed.json()["state"] == "degraded"
        assert allowed.json()["reason"] == "MCP server or SSE transport is not initialized"
        assert allowed.json()["transport_available"] is False

    def test_sse_reports_structured_degraded_state_without_transport(self) -> None:
        app = _build_route_app()
        client = TestClient(app)

        with client.stream("GET", "/v1/mcp/sse", headers=_make_headers("agents:read")) as resp:
            assert resp.status_code == 200
            body = resp.read().decode("utf-8")

        assert "event: endpoint" in body
        assert '"messages_endpoint": "/v1/mcp/messages"' in body
        assert "event: status" in body
        assert '"state": "degraded"' in body
        assert '"available": false' in body
        assert '"reason": "MCP server or SSE transport is not initialized"' in body

    def test_messages_fail_closed_without_transport(self) -> None:
        app = _build_route_app()
        client = TestClient(app)

        resp = client.post(
            "/v1/mcp/messages",
            content=b'{"jsonrpc":"2.0"}',
            headers=_make_headers("agents:read"),
        )

        assert resp.status_code == 503
        assert resp.json()["detail"] == {
            "status": "unavailable",
            "reason": "MCP transport not initialized",
            "messages_endpoint": "/v1/mcp/messages",
        }

    def test_status_reports_unavailable_when_bridge_missing(self) -> None:
        app = _build_route_app()
        del app.state.mcp_bridge
        client = TestClient(app)

        resp = client.get("/v1/mcp/status", headers=_make_headers("agents:read"))

        assert resp.status_code == 200
        assert resp.json() == {
            "available": False,
            "state": "unavailable",
            "mcp_sdk_installed": False,
            "transport_available": False,
            "reason": "MCP bridge is not initialized",
        }

    def test_routes_reuse_persistent_transport(self) -> None:
        app = _build_route_app()
        transport = _FakeTransport()
        server = _FakeMCPServer()
        app.state.mcp_transport = transport
        app.state.mcp_server = server

        with TestClient(app) as client:
            with client.stream(
                "GET", "/v1/mcp/sse", headers=_make_headers("agents:read")
            ) as sse_response:
                assert sse_response.status_code == 200
                sse_response.read()

            message_response = client.post(
                "/v1/mcp/messages",
                content=b'{"jsonrpc":"2.0"}',
                headers=_make_headers("agents:read"),
            )
            assert message_response.status_code == 200
            assert message_response.json() == {"status": "processed"}

            status_response = client.get("/v1/mcp/status", headers=_make_headers("agents:read"))
            assert status_response.status_code == 200
            assert status_response.json()["available"] is True
            assert status_response.json()["state"] == "available"
            assert status_response.json()["transport_available"] is True

        assert app.state.mcp_transport is transport
        assert len(transport.connect_calls) == 1
        assert len(transport.message_calls) == 1
        server.run.assert_awaited_once()


class TestMCPServiceBridge:
    def test_creation_with_workflow_registry(self) -> None:
        from agent33.mcp_server.bridge import MCPServiceBridge

        workflow_registry = {"release": MagicMock()}
        bridge = MCPServiceBridge(workflow_registry=workflow_registry)

        assert bridge.workflow_registry is workflow_registry
        assert bridge.get_workflow("release") is workflow_registry["release"]

    def test_system_status_counts_workflows(self) -> None:
        from agent33.mcp_server.bridge import MCPServiceBridge

        bridge = MCPServiceBridge(workflow_registry={"one": MagicMock(), "two": MagicMock()})
        status = bridge.get_system_status()

        assert status["status"] == "operational"
        assert status["workflows_loaded"] == 2

    async def test_execute_tool_runs_governance_and_validated_execute(self) -> None:
        from agent33.mcp_server.bridge import MCPServiceBridge
        from agent33.mcp_server.tools import handle_execute_tool
        from agent33.tools.base import ToolContext, ToolResult

        tool_registry = MagicMock()
        tool_registry.get.return_value = object()
        tool_registry.validated_execute = AsyncMock(return_value=ToolResult.ok("patched"))
        governance = MagicMock()
        governance.pre_execute_check.return_value = True
        governance.log_execution = MagicMock()

        result = await handle_execute_tool(
            MCPServiceBridge(tool_registry=tool_registry, tool_governance=governance),
            tool_name="apply_patch",
            arguments={"patch": "*** Begin Patch\n*** End Patch"},
            context=ToolContext(user_scopes=["tools:execute"]),
        )

        assert result["success"] is True
        tool_registry.validated_execute.assert_awaited_once()
        governance.pre_execute_check.assert_called_once()
        governance.log_execution.assert_called_once()

    async def test_execute_tool_returns_governance_error_when_blocked(self) -> None:
        from agent33.mcp_server.bridge import MCPServiceBridge
        from agent33.mcp_server.tools import handle_execute_tool
        from agent33.tools.base import ToolContext

        tool_registry = MagicMock()
        tool_registry.get.return_value = object()
        tool_registry.validated_execute = AsyncMock()
        governance = MagicMock()
        governance.pre_execute_check.return_value = False

        result = await handle_execute_tool(
            MCPServiceBridge(tool_registry=tool_registry, tool_governance=governance),
            tool_name="apply_patch",
            arguments={"patch": "*** Begin Patch\n*** End Patch"},
            context=ToolContext(user_scopes=["tools:execute"]),
        )

        assert result["success"] is False
        assert "blocked by governance policy" in result["error"]
        tool_registry.validated_execute.assert_not_called()


class TestMCPServerCreation:
    def test_create_server_without_sdk(self) -> None:
        from agent33.mcp_server.bridge import MCPServiceBridge
        from agent33.mcp_server.server import create_mcp_server

        bridge = MCPServiceBridge()
        with patch("agent33.mcp_server.server._HAS_MCP", False):
            server = create_mcp_server(bridge)
            assert server is None

    async def test_execute_tool_uses_request_context_for_auth_and_tool_context(self) -> None:
        from agent33.mcp_server.bridge import MCPServiceBridge
        from agent33.mcp_server.server import create_mcp_server
        from agent33.security.auth import TokenPayload

        request = SimpleNamespace(
            state=SimpleNamespace(
                user=TokenPayload(sub="tool-user", scopes=["tools:execute"], tenant_id="tenant-1")
            )
        )
        fake_server = _RecordingServer(request=request)

        with (
            patch("agent33.mcp_server.server._HAS_MCP", True),
            patch("agent33.mcp_server.server.Server", return_value=fake_server, create=True),
            patch(
                "agent33.mcp_server.server.Tool",
                side_effect=lambda **kwargs: _ToolDescriptor(**kwargs),
                create=True,
            ),
            patch(
                "agent33.mcp_server.server.TextContent",
                side_effect=lambda **kwargs: _TextContent(**kwargs),
                create=True,
            ),
            patch("agent33.mcp_server.server.register_resources"),
            patch(
                "agent33.mcp_server.tools.handle_execute_tool", new_callable=AsyncMock
            ) as exec_tool,
        ):
            exec_tool.return_value = {"success": True}
            tool_registry = MagicMock()
            tool_registry.get.return_value = object()
            tool_registry.get_entry.return_value = None
            create_mcp_server(MCPServiceBridge(tool_registry=tool_registry))
            await fake_server.handlers["call_tool"](
                "execute_tool",
                {"tool_name": "shell", "arguments": {"command": "echo hi"}},
            )

        kwargs = exec_tool.await_args.kwargs
        context = kwargs["context"]
        assert kwargs["tool_name"] == "shell"
        assert context.user_scopes == ["tools:execute"]
        assert context.requested_by == "tool-user"
        assert context.tenant_id == "tenant-1"

    async def test_tool_call_rejects_missing_scope(self) -> None:
        from agent33.mcp_server.server import create_mcp_server
        from agent33.security.auth import TokenPayload

        request = SimpleNamespace(
            state=SimpleNamespace(user=TokenPayload(sub="reader", scopes=["agents:read"]))
        )
        fake_server = _RecordingServer(request=request)

        with (
            patch("agent33.mcp_server.server._HAS_MCP", True),
            patch("agent33.mcp_server.server.Server", return_value=fake_server, create=True),
            patch(
                "agent33.mcp_server.server.Tool",
                side_effect=lambda **kwargs: _ToolDescriptor(**kwargs),
                create=True,
            ),
            patch(
                "agent33.mcp_server.server.TextContent",
                side_effect=lambda **kwargs: _TextContent(**kwargs),
                create=True,
            ),
            patch("agent33.mcp_server.server.register_resources"),
        ):
            create_mcp_server(MagicMock(spec=object))

        try:
            await fake_server.handlers["call_tool"]("execute_tool", {"tool_name": "shell"})
        except PermissionError as exc:
            assert "tools:execute" in str(exc)
        else:
            raise AssertionError("expected PermissionError")

    async def test_list_tools_only_returns_scoped_mcp_tools(self) -> None:
        from agent33.mcp_server.server import create_mcp_server
        from agent33.security.auth import TokenPayload

        request = SimpleNamespace(
            state=SimpleNamespace(user=TokenPayload(sub="reader", scopes=["agents:read"]))
        )
        fake_server = _RecordingServer(request=request)

        with (
            patch("agent33.mcp_server.server._HAS_MCP", True),
            patch("agent33.mcp_server.server.Server", return_value=fake_server, create=True),
            patch(
                "agent33.mcp_server.server.Tool",
                side_effect=lambda **kwargs: _ToolDescriptor(**kwargs),
                create=True,
            ),
            patch(
                "agent33.mcp_server.server.TextContent",
                side_effect=lambda **kwargs: _TextContent(**kwargs),
                create=True,
            ),
            patch("agent33.mcp_server.server.register_resources"),
        ):
            create_mcp_server(MagicMock(spec=object))

        tools = await fake_server.handlers["list_tools"]()
        tool_names = {tool.name for tool in tools}

        assert "list_agents" in tool_names
        assert "execute_tool" not in tool_names

    async def test_list_tools_includes_proxy_tools_for_tools_execute_scope(self) -> None:
        from agent33.mcp_server.bridge import MCPServiceBridge
        from agent33.mcp_server.server import create_mcp_server
        from agent33.security.auth import TokenPayload

        request = SimpleNamespace(
            state=SimpleNamespace(user=TokenPayload(sub="executor", scopes=["tools:execute"]))
        )
        fake_server = _RecordingServer(request=request)
        proxy_manager = ProxyManager()
        handle = ChildServerHandle(ProxyServerConfig(id="fs", command="echo", tool_prefix="fs"))
        handle.state = ChildServerState.HEALTHY
        handle.register_tools([ProxyToolDefinition(name="read_file", description="Read file")])
        proxy_manager._children["fs"] = handle

        with (
            patch("agent33.mcp_server.server._HAS_MCP", True),
            patch("agent33.mcp_server.server.Server", return_value=fake_server, create=True),
            patch(
                "agent33.mcp_server.server.Tool",
                side_effect=lambda **kwargs: _ToolDescriptor(**kwargs),
                create=True,
            ),
            patch(
                "agent33.mcp_server.server.TextContent",
                side_effect=lambda **kwargs: _TextContent(**kwargs),
                create=True,
            ),
            patch("agent33.mcp_server.server.register_resources"),
        ):
            create_mcp_server(MCPServiceBridge(proxy_manager=proxy_manager))

        tools = await fake_server.handlers["list_tools"]()
        tool_names = {tool.name for tool in tools}
        assert "fs__read_file" in tool_names
        assert "discover_tools" in tool_names

    async def test_execute_tool_rejects_unknown_registry_tool(self) -> None:
        from agent33.mcp_server.bridge import MCPServiceBridge
        from agent33.mcp_server.server import create_mcp_server
        from agent33.security.auth import TokenPayload

        request = SimpleNamespace(
            state=SimpleNamespace(user=TokenPayload(sub="executor", scopes=["tools:execute"]))
        )
        fake_server = _RecordingServer(request=request)

        with (
            patch("agent33.mcp_server.server._HAS_MCP", True),
            patch("agent33.mcp_server.server.Server", return_value=fake_server, create=True),
            patch(
                "agent33.mcp_server.server.Tool",
                side_effect=lambda **kwargs: _ToolDescriptor(**kwargs),
                create=True,
            ),
            patch(
                "agent33.mcp_server.server.TextContent",
                side_effect=lambda **kwargs: _TextContent(**kwargs),
                create=True,
            ),
            patch("agent33.mcp_server.server.register_resources"),
        ):
            tool_registry = MagicMock()
            tool_registry.get.return_value = None
            tool_registry.get_entry.return_value = None
            create_mcp_server(MCPServiceBridge(tool_registry=tool_registry))

        with pytest.raises(PermissionError, match="not allowed"):
            await fake_server.handlers["call_tool"](
                "execute_tool",
                {"tool_name": "missing-tool", "arguments": {}},
            )

    async def test_call_tool_routes_proxy_tools(self) -> None:
        from agent33.mcp_server.bridge import MCPServiceBridge
        from agent33.mcp_server.server import create_mcp_server
        from agent33.security.auth import TokenPayload

        request = SimpleNamespace(
            state=SimpleNamespace(user=TokenPayload(sub="executor", scopes=["tools:execute"]))
        )
        fake_server = _RecordingServer(request=request)
        proxy_manager = ProxyManager()
        handle = ChildServerHandle(ProxyServerConfig(id="fs", command="echo", tool_prefix="fs"))
        handle.state = ChildServerState.HEALTHY
        handle.register_tools([ProxyToolDefinition(name="read_file", description="Read file")])
        handle._call_handler = AsyncMock(return_value={"status": "ok", "source": "proxy"})
        proxy_manager._children["fs"] = handle

        with (
            patch("agent33.mcp_server.server._HAS_MCP", True),
            patch("agent33.mcp_server.server.Server", return_value=fake_server, create=True),
            patch(
                "agent33.mcp_server.server.Tool",
                side_effect=lambda **kwargs: _ToolDescriptor(**kwargs),
                create=True,
            ),
            patch(
                "agent33.mcp_server.server.TextContent",
                side_effect=lambda **kwargs: _TextContent(**kwargs),
                create=True,
            ),
            patch("agent33.mcp_server.server.register_resources"),
        ):
            create_mcp_server(MCPServiceBridge(proxy_manager=proxy_manager))

        result = await fake_server.handlers["call_tool"]("fs__read_file", {"path": "/tmp/x"})
        assert result[0].text == '{"status": "ok", "source": "proxy"}'

    async def test_discover_tools_routes_to_discovery_service(self) -> None:
        from agent33.discovery.service import ToolDiscoveryMatch
        from agent33.mcp_server.bridge import MCPServiceBridge
        from agent33.mcp_server.server import create_mcp_server
        from agent33.security.auth import TokenPayload
        from agent33.tools.discovery_runtime import ToolActivationManager

        request = SimpleNamespace(
            headers={"x-agent-session-id": "session-1"},
            state=SimpleNamespace(
                user=TokenPayload(sub="executor", scopes=["tools:execute"], tenant_id="tenant-1")
            ),
        )
        fake_server = _RecordingServer(request=request)
        discovery_service = MagicMock()
        discovery_service.discover_tools.return_value = [
            ToolDiscoveryMatch(name="shell", description="Run commands", score=9.0)
        ]

        with (
            patch("agent33.mcp_server.server._HAS_MCP", True),
            patch("agent33.mcp_server.server.Server", return_value=fake_server, create=True),
            patch(
                "agent33.mcp_server.server.Tool",
                side_effect=lambda **kwargs: _ToolDescriptor(**kwargs),
                create=True,
            ),
            patch(
                "agent33.mcp_server.server.TextContent",
                side_effect=lambda **kwargs: _TextContent(**kwargs),
                create=True,
            ),
            patch("agent33.mcp_server.server.register_resources"),
        ):
            create_mcp_server(
                MCPServiceBridge(
                    discovery_service=discovery_service,
                    tool_activation_manager=ToolActivationManager(),
                    tool_discovery_mode="dynamic",
                )
            )

        result = await fake_server.handlers["call_tool"](
            "discover_tools",
            {"query": "shell", "limit": 5, "activation_limit": 1},
        )

        payload = json.loads(result[0].text)
        assert payload["query"] == "shell"
        assert payload["activated"] == ["shell"]
        assert payload["activation_state"] == "activated"
        assert payload["matches"] == [
            {
                "name": "shell",
                "description": "Run commands",
                "score": 9.0,
                "status": "active",
                "version": "",
                "tags": [],
            }
        ]
        discovery_service.discover_tools.assert_called_once_with("shell", limit=5)

    async def test_discover_tools_normalizes_invalid_numeric_arguments(self) -> None:
        from agent33.discovery.service import ToolDiscoveryMatch
        from agent33.mcp_server.bridge import MCPServiceBridge
        from agent33.mcp_server.server import create_mcp_server
        from agent33.security.auth import TokenPayload
        from agent33.tools.discovery_runtime import ToolActivationManager

        request = SimpleNamespace(
            headers={"x-agent-session-id": "session-1"},
            state=SimpleNamespace(
                user=TokenPayload(sub="executor", scopes=["tools:execute"], tenant_id="tenant-1")
            ),
        )
        fake_server = _RecordingServer(request=request)
        discovery_service = MagicMock()
        discovery_service.discover_tools.return_value = [
            ToolDiscoveryMatch(name="shell", description="Run commands", score=9.0)
        ]

        with (
            patch("agent33.mcp_server.server._HAS_MCP", True),
            patch("agent33.mcp_server.server.Server", return_value=fake_server, create=True),
            patch(
                "agent33.mcp_server.server.Tool",
                side_effect=lambda **kwargs: _ToolDescriptor(**kwargs),
                create=True,
            ),
            patch(
                "agent33.mcp_server.server.TextContent",
                side_effect=lambda **kwargs: _TextContent(**kwargs),
                create=True,
            ),
            patch("agent33.mcp_server.server.register_resources"),
        ):
            create_mcp_server(
                MCPServiceBridge(
                    discovery_service=discovery_service,
                    tool_activation_manager=ToolActivationManager(),
                    tool_discovery_mode="dynamic",
                )
            )

        result = await fake_server.handlers["call_tool"](
            "discover_tools",
            {"query": "shell", "limit": "bogus", "activation_limit": None},
        )

        payload = json.loads(result[0].text)
        assert payload["activated"] == ["shell"]
        assert payload["activation_state"] == "activated"
        discovery_service.discover_tools.assert_called_once_with("shell", limit=10)

    async def test_runtime_list_tools_reflects_dynamic_session_activation(self) -> None:
        from agent33.mcp_server.bridge import MCPServiceBridge
        from agent33.mcp_server.server import create_mcp_server
        from agent33.security.auth import TokenPayload
        from agent33.tools.discovery_runtime import (
            DISCOVER_TOOLS_TOOL_NAME,
            ToolActivationManager,
        )
        from agent33.tools.registry import ToolRegistry
        from agent33.tools.registry_entry import ToolRegistryEntry

        class _StaticTool:
            def __init__(self, name: str, description: str) -> None:
                self.name = name
                self.description = description

            async def execute(self, params, context):  # type: ignore[no-untyped-def]
                return None

        request = SimpleNamespace(
            headers={"x-agent-session-id": "session-1"},
            state=SimpleNamespace(
                user=TokenPayload(
                    sub="executor",
                    scopes=["agents:read", "tools:execute"],
                    tenant_id="tenant-1",
                )
            ),
        )
        fake_server = _RecordingServer(request=request)
        tool_registry = ToolRegistry()
        tool_registry.register_with_entry(
            _StaticTool(DISCOVER_TOOLS_TOOL_NAME, "Discover tools"),
            ToolRegistryEntry(
                tool_id=DISCOVER_TOOLS_TOOL_NAME,
                name=DISCOVER_TOOLS_TOOL_NAME,
                version="1.0.0",
                description="Discover tools",
            ),
        )
        tool_registry.register_with_entry(
            _StaticTool("shell", "Run commands"),
            ToolRegistryEntry(
                tool_id="shell",
                name="shell",
                version="1.0.0",
                description="Run commands",
            ),
        )
        tool_registry.register_with_entry(
            _StaticTool("file_ops", "Read files"),
            ToolRegistryEntry(
                tool_id="file_ops",
                name="file_ops",
                version="1.0.0",
                description="Read files",
            ),
        )

        activation_manager = ToolActivationManager()

        with (
            patch("agent33.mcp_server.server._HAS_MCP", True),
            patch("agent33.mcp_server.server.Server", return_value=fake_server, create=True),
            patch(
                "agent33.mcp_server.server.Tool",
                side_effect=lambda **kwargs: _ToolDescriptor(**kwargs),
                create=True,
            ),
            patch(
                "agent33.mcp_server.server.TextContent",
                side_effect=lambda **kwargs: _TextContent(**kwargs),
                create=True,
            ),
            patch("agent33.mcp_server.server.register_resources"),
        ):
            create_mcp_server(
                MCPServiceBridge(
                    tool_registry=tool_registry,
                    tool_activation_manager=activation_manager,
                    tool_discovery_mode="dynamic",
                )
            )

        initial = await fake_server.handlers["call_tool"]("list_tools", {})
        assert initial[0].text == ('[{"name": "discover_tools", "description": "Discover tools"}]')

        activation_manager.activate_tools(["shell"], tenant_id="tenant-1", session_id="session-1")

        after_activation = await fake_server.handlers["call_tool"]("list_tools", {})
        assert after_activation[0].text == (
            '[{"name": "discover_tools", "description": "Discover tools"}, '
            '{"name": "shell", "description": "Run commands"}]'
        )

    async def test_resolve_workflow_routes_to_discovery_service(self) -> None:
        from agent33.mcp_server.bridge import MCPServiceBridge
        from agent33.mcp_server.server import create_mcp_server
        from agent33.security.auth import TokenPayload

        request = SimpleNamespace(
            state=SimpleNamespace(
                user=TokenPayload(sub="reader", scopes=["workflows:read"], tenant_id="tenant-1")
            )
        )
        fake_server = _RecordingServer(request=request)
        discovery_service = MagicMock()
        discovery_service.resolve_workflow.return_value = [
            SimpleNamespace(
                model_dump=lambda **_: {
                    "name": "release",
                    "source": "runtime",
                    "score": 10.0,
                }
            )
        ]

        with (
            patch("agent33.mcp_server.server._HAS_MCP", True),
            patch("agent33.mcp_server.server.Server", return_value=fake_server, create=True),
            patch(
                "agent33.mcp_server.server.Tool",
                side_effect=lambda **kwargs: _ToolDescriptor(**kwargs),
                create=True,
            ),
            patch(
                "agent33.mcp_server.server.TextContent",
                side_effect=lambda **kwargs: _TextContent(**kwargs),
                create=True,
            ),
            patch("agent33.mcp_server.server.register_resources"),
        ):
            create_mcp_server(MCPServiceBridge(discovery_service=discovery_service))

        result = await fake_server.handlers["call_tool"](
            "resolve_workflow",
            {"query": "release", "limit": 3},
        )

        assert result[0].text == (
            '{"query": "release", "matches": [{"name": "release", '
            '"source": "runtime", "score": 10.0}]}'
        )
        discovery_service.resolve_workflow.assert_called_once_with(
            "release",
            limit=3,
            tenant_id="tenant-1",
        )

    async def test_resolve_workflow_omits_tenant_filter_for_admin(self) -> None:
        from agent33.mcp_server.bridge import MCPServiceBridge
        from agent33.mcp_server.server import create_mcp_server
        from agent33.security.auth import TokenPayload

        request = SimpleNamespace(
            state=SimpleNamespace(
                user=TokenPayload(sub="admin-user", scopes=["admin"], tenant_id="tenant-1")
            )
        )
        fake_server = _RecordingServer(request=request)
        discovery_service = MagicMock()
        discovery_service.resolve_workflow.return_value = []

        with (
            patch("agent33.mcp_server.server._HAS_MCP", True),
            patch("agent33.mcp_server.server.Server", return_value=fake_server, create=True),
            patch(
                "agent33.mcp_server.server.Tool",
                side_effect=lambda **kwargs: _ToolDescriptor(**kwargs),
                create=True,
            ),
            patch(
                "agent33.mcp_server.server.TextContent",
                side_effect=lambda **kwargs: _TextContent(**kwargs),
                create=True,
            ),
            patch("agent33.mcp_server.server.register_resources"),
        ):
            create_mcp_server(MCPServiceBridge(discovery_service=discovery_service))

        await fake_server.handlers["call_tool"](
            "resolve_workflow",
            {"query": "deploy", "limit": 2},
        )

        discovery_service.resolve_workflow.assert_called_once_with(
            "deploy",
            limit=2,
            tenant_id=None,
        )

    async def test_resolve_workflow_requires_tenant_for_non_admin(self) -> None:
        from agent33.mcp_server.bridge import MCPServiceBridge
        from agent33.mcp_server.server import create_mcp_server
        from agent33.security.auth import TokenPayload

        request = SimpleNamespace(
            state=SimpleNamespace(
                user=TokenPayload(sub="reader", scopes=["workflows:read"], tenant_id="")
            )
        )
        fake_server = _RecordingServer(request=request)
        discovery_service = MagicMock()
        discovery_service.resolve_workflow.return_value = []

        with (
            patch("agent33.mcp_server.server._HAS_MCP", True),
            patch("agent33.mcp_server.server.Server", return_value=fake_server, create=True),
            patch(
                "agent33.mcp_server.server.Tool",
                side_effect=lambda **kwargs: _ToolDescriptor(**kwargs),
                create=True,
            ),
            patch(
                "agent33.mcp_server.server.TextContent",
                side_effect=lambda **kwargs: _TextContent(**kwargs),
                create=True,
            ),
            patch("agent33.mcp_server.server.register_resources"),
        ):
            create_mcp_server(MCPServiceBridge(discovery_service=discovery_service))

        result = await fake_server.handlers["call_tool"](
            "resolve_workflow",
            {"query": "deploy", "limit": 2},
        )

        assert result[0].text == (
            '{"query": "deploy", "matches": [], '
            '"error": "tenant_id is required for non-admin requests"}'
        )
        discovery_service.resolve_workflow.assert_not_called()

    async def test_discover_skills_omits_tenant_filter_for_admin(self) -> None:
        from agent33.mcp_server.bridge import MCPServiceBridge
        from agent33.mcp_server.server import create_mcp_server
        from agent33.security.auth import TokenPayload

        request = SimpleNamespace(
            state=SimpleNamespace(
                user=TokenPayload(sub="admin-user", scopes=["admin"], tenant_id="tenant-1")
            )
        )
        fake_server = _RecordingServer(request=request)
        discovery_service = MagicMock()
        discovery_service.discover_skills.return_value = []

        with (
            patch("agent33.mcp_server.server._HAS_MCP", True),
            patch("agent33.mcp_server.server.Server", return_value=fake_server, create=True),
            patch(
                "agent33.mcp_server.server.Tool",
                side_effect=lambda **kwargs: _ToolDescriptor(**kwargs),
                create=True,
            ),
            patch(
                "agent33.mcp_server.server.TextContent",
                side_effect=lambda **kwargs: _TextContent(**kwargs),
                create=True,
            ),
            patch("agent33.mcp_server.server.register_resources"),
        ):
            create_mcp_server(MCPServiceBridge(discovery_service=discovery_service))

        await fake_server.handlers["call_tool"](
            "discover_skills",
            {"query": "deploy", "limit": 5},
        )

        discovery_service.discover_skills.assert_called_once_with(
            "deploy",
            limit=5,
            tenant_id=None,
        )
