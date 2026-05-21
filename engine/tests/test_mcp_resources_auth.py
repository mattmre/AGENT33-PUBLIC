"""Tests for MCP auth helpers and handler-level scope enforcement."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent33.security.auth import TokenPayload


def _make_server(*scopes: str):
    request = SimpleNamespace(
        state=SimpleNamespace(user=TokenPayload(sub="tester", scopes=list(scopes)))
    )
    return SimpleNamespace(request_context=SimpleNamespace(request=request))


class TestMCPAuthMappings:
    def test_tool_scope_mapping_uses_existing_permissions(self) -> None:
        from agent33.mcp_server.auth import get_required_scope_for_tool

        assert get_required_scope_for_tool("list_agents") == "agents:read"
        assert get_required_scope_for_tool("invoke_agent") == "agents:invoke"
        assert get_required_scope_for_tool("discover_tools") == "tools:execute"
        assert get_required_scope_for_tool("discover_skills") == "agents:read"
        assert get_required_scope_for_tool("resolve_workflow") == "workflows:read"
        assert get_required_scope_for_tool("execute_tool") == "tools:execute"

    def test_proxy_tool_mapping_honors_custom_separator(self) -> None:
        from agent33.mcp_server.auth import get_required_scope_for_tool

        assert get_required_scope_for_tool("fs.read_file", tool_separator=".") == "tools:execute"

    def test_resource_scope_mapping_covers_documented_contract(self) -> None:
        from agent33.mcp_server.auth import get_required_scope_for_resource

        assert get_required_scope_for_resource("agent33://agent-registry") == "agents:read"
        assert (
            get_required_scope_for_resource("agent33://policy-pack") == "component-security:read"
        )
        assert (
            get_required_scope_for_resource("agent33://pricing-catalog")
            == "component-security:read"
        )
        assert get_required_scope_for_resource("agent33://agents/AGT-001") == "agents:read"
        assert get_required_scope_for_resource("agent33://workflows/release") == "workflows:read"


class TestMCPAuthEnforcement:
    def test_enforce_tool_scope_reads_scopes_from_request_context(self) -> None:
        from agent33.mcp_server.auth import enforce_tool_scope

        enforce_tool_scope(_make_server("tools:execute"), "execute_tool")

    def test_enforce_tool_scope_raises_without_required_scope(self) -> None:
        from agent33.mcp_server.auth import enforce_tool_scope

        with pytest.raises(PermissionError, match="tools:execute"):
            enforce_tool_scope(_make_server("agents:read"), "execute_tool")

    def test_enforce_resource_scope_raises_without_required_scope(self) -> None:
        from agent33.mcp_server.auth import enforce_resource_scope

        with pytest.raises(PermissionError, match="workflows:read"):
            enforce_resource_scope(_make_server("agents:read"), "agent33://workflows/release")

    def test_enforce_resource_scope_allows_component_security_policy_pack(self) -> None:
        from agent33.mcp_server.auth import enforce_resource_scope

        enforce_resource_scope(_make_server("component-security:read"), "agent33://policy-pack")

    def test_enforce_resource_scope_allows_component_security_pricing_catalog(self) -> None:
        from agent33.mcp_server.auth import enforce_resource_scope

        enforce_resource_scope(
            _make_server("component-security:read"), "agent33://pricing-catalog"
        )

    def test_unknown_tool_defaults_to_deny(self) -> None:
        from agent33.mcp_server.auth import enforce_tool_scope

        with pytest.raises(PermissionError, match="not allowed"):
            enforce_tool_scope(_make_server("admin"), "unknown_tool")

    def test_unknown_resource_defaults_to_deny(self) -> None:
        from agent33.mcp_server.auth import enforce_resource_scope

        with pytest.raises(PermissionError, match="not allowed"):
            enforce_resource_scope(_make_server("admin"), "agent33://unknown/resource")

    def test_enforce_scope_requires_authenticated_request(self) -> None:
        from agent33.mcp_server.auth import enforce_tool_scope

        server = SimpleNamespace(
            request_context=SimpleNamespace(request=SimpleNamespace(state=object()))
        )
        with pytest.raises(PermissionError, match="not authenticated"):
            enforce_tool_scope(server, "list_agents")

    def test_get_server_request_returns_none_without_active_request_context(self) -> None:
        from agent33.mcp_server.auth import get_server_request

        class _LookupErrorServer:
            @property
            def request_context(self) -> object:
                raise LookupError("no active request")

        assert get_server_request(_LookupErrorServer()) is None


class _MockMCPServer:
    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}

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


class _Resource(SimpleNamespace):
    pass


class _ResourceTemplate(SimpleNamespace):
    pass


class TestResourceReadHandlerAuth:
    async def test_registered_resource_handler_enforces_scope_before_read(self) -> None:
        from agent33.mcp_server import resources as resources_mod
        from agent33.mcp_server.bridge import MCPServiceBridge

        server = _MockMCPServer()

        def _before_read(uri: str) -> None:
            raise PermissionError(f"blocked {uri}")

        with (
            patch.object(resources_mod, "_HAS_MCP", True),
            patch.object(
                resources_mod,
                "Resource",
                side_effect=lambda **kwargs: _Resource(**kwargs),
                create=True,
            ),
            patch.object(
                resources_mod,
                "ResourceTemplate",
                side_effect=lambda **kwargs: _ResourceTemplate(**kwargs),
                create=True,
            ),
        ):
            resources_mod.register_resources(
                server,
                MCPServiceBridge(
                    workflow_registry={"release": SimpleNamespace(model_dump=lambda **_: {})}
                ),
                before_read=_before_read,
            )

        with pytest.raises(PermissionError, match="agent33://workflows/release"):
            await server.handlers["read_resource"]("agent33://workflows/release")

    async def test_registered_resource_listing_filters_unauthorized_items(self) -> None:
        from agent33.mcp_server import resources as resources_mod
        from agent33.mcp_server.bridge import MCPServiceBridge

        server = _MockMCPServer()

        def _before_list(identifier: str) -> None:
            if identifier in {"agent33://policy-pack", "agent33://pricing-catalog"}:
                raise PermissionError("blocked")

        with (
            patch.object(resources_mod, "_HAS_MCP", True),
            patch.object(
                resources_mod,
                "Resource",
                side_effect=lambda **kwargs: _Resource(**kwargs),
                create=True,
            ),
            patch.object(
                resources_mod,
                "ResourceTemplate",
                side_effect=lambda **kwargs: _ResourceTemplate(**kwargs),
                create=True,
            ),
        ):
            resources_mod.register_resources(
                server,
                MCPServiceBridge(),
                before_list=_before_list,
            )

        resources = await server.handlers["list_resources"]()
        assert all(str(resource.uri) != "agent33://policy-pack" for resource in resources)
        assert all(str(resource.uri) != "agent33://pricing-catalog" for resource in resources)
