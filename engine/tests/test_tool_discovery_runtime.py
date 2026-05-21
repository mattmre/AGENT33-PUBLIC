"""Tests for dynamic tool activation and session-scoped visibility."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from agent33.discovery.service import ToolDiscoveryMatch
from agent33.tools.base import ToolContext, ToolResult
from agent33.tools.discovery_runtime import (
    DISCOVER_TOOLS_TOOL_NAME,
    DiscoverToolsTool,
    SessionToolRegistryView,
    ToolActivationManager,
)
from agent33.tools.registry import ToolRegistry
from agent33.tools.registry_entry import ToolRegistryEntry


class _StaticTool:
    def __init__(self, name: str, description: str = "") -> None:
        self._name = name
        self._description = description or f"{name} description"

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    async def execute(self, params: dict[str, object], context: ToolContext) -> ToolResult:
        return ToolResult.ok(json.dumps({"tool": self._name, "params": params}))


def _register_tool(registry: ToolRegistry, tool: _StaticTool | DiscoverToolsTool) -> None:
    registry.register_with_entry(
        tool,
        ToolRegistryEntry(
            tool_id=tool.name,
            name=tool.name,
            version="1.0.0",
            description=tool.description,
            parameters_schema=getattr(tool, "parameters_schema", {}),
        ),
    )


class TestSessionToolRegistryView:
    def test_dynamic_mode_only_exposes_discover_and_activated_tools(self) -> None:
        registry = ToolRegistry()
        _register_tool(registry, _StaticTool(DISCOVER_TOOLS_TOOL_NAME))
        _register_tool(registry, _StaticTool("shell"))
        _register_tool(registry, _StaticTool("file_ops"))

        activation_manager = ToolActivationManager()
        activation_manager.activate_tools(["shell"], tenant_id="tenant-1", session_id="session-1")

        view = SessionToolRegistryView(
            registry,
            mode="dynamic",
            activation_manager=activation_manager,
            context=ToolContext(tenant_id="tenant-1", session_id="session-1"),
        )

        assert [tool.name for tool in view.list_all()] == [DISCOVER_TOOLS_TOOL_NAME, "shell"]

    def test_dynamic_mode_falls_back_to_full_visibility_without_session(self) -> None:
        registry = ToolRegistry()
        _register_tool(registry, _StaticTool(DISCOVER_TOOLS_TOOL_NAME))
        _register_tool(registry, _StaticTool("shell"))
        _register_tool(registry, _StaticTool("file_ops"))

        view = SessionToolRegistryView(
            registry,
            mode="dynamic",
            activation_manager=ToolActivationManager(),
            context=ToolContext(tenant_id="tenant-1"),
        )

        assert [tool.name for tool in view.list_all()] == ["shell", "file_ops"]

    def test_dynamic_mode_uses_requester_scope_when_tenant_missing(self) -> None:
        registry = ToolRegistry()
        _register_tool(registry, _StaticTool(DISCOVER_TOOLS_TOOL_NAME))
        _register_tool(registry, _StaticTool("shell"))

        activation_manager = ToolActivationManager()
        activation_manager.activate_tools(
            ["shell"],
            requested_by="user-a",
            session_id="session-1",
        )

        user_a_view = SessionToolRegistryView(
            registry,
            mode="dynamic",
            activation_manager=activation_manager,
            context=ToolContext(requested_by="user-a", session_id="session-1"),
        )
        user_b_view = SessionToolRegistryView(
            registry,
            mode="dynamic",
            activation_manager=activation_manager,
            context=ToolContext(requested_by="user-b", session_id="session-1"),
        )

        assert [tool.name for tool in user_a_view.list_all()] == [
            DISCOVER_TOOLS_TOOL_NAME,
            "shell",
        ]
        assert [tool.name for tool in user_b_view.list_all()] == [DISCOVER_TOOLS_TOOL_NAME]

    async def test_exact_name_execution_still_works_for_hidden_tool(self) -> None:
        registry = ToolRegistry()
        _register_tool(registry, _StaticTool(DISCOVER_TOOLS_TOOL_NAME))
        _register_tool(registry, _StaticTool("shell"))

        view = SessionToolRegistryView(
            registry,
            mode="dynamic",
            activation_manager=ToolActivationManager(),
            context=ToolContext(tenant_id="tenant-1", session_id="session-1"),
        )

        assert [tool.name for tool in view.list_all()] == [DISCOVER_TOOLS_TOOL_NAME]
        result = await view.validated_execute(
            "shell",
            {"command": "echo hi"},
            ToolContext(tenant_id="tenant-1", session_id="session-1"),
        )

        assert result.success is True
        assert '"tool": "shell"' in result.output


class TestDiscoverToolsTool:
    async def test_execute_activates_top_matches_for_session(self) -> None:
        discovery_service = MagicMock()
        discovery_service.discover_tools.return_value = [
            ToolDiscoveryMatch(name="shell", description="Run commands", score=9.0),
            ToolDiscoveryMatch(name="file_ops", description="Read files", score=8.0),
        ]
        activation_manager = ToolActivationManager()
        tool = DiscoverToolsTool(
            discovery_service=discovery_service,
            activation_manager=activation_manager,
            mode="dynamic",
        )

        result = await tool.execute(
            {"query": "run shell commands", "activation_limit": 1},
            ToolContext(tenant_id="tenant-1", session_id="session-1"),
        )

        assert result.success is True
        payload = json.loads(result.output)
        assert payload["activated"] == ["shell"]
        assert payload["activation_state"] == "activated"
        assert activation_manager.list_active_tools(
            tenant_id="tenant-1",
            session_id="session-1",
        ) == ["shell"]
