"""Tests for the documented MCP resource contract."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from agent33.agents.definition import AgentCapability, AgentDefinition, AgentRole
from agent33.agents.registry import AgentRegistry
from agent33.llm.pricing import CostSource, PricingCatalog, PricingEntry
from agent33.mcp_server.bridge import MCPServiceBridge
from agent33.mcp_server.proxy_child import ChildServerHandle, ChildServerState, ProxyToolDefinition
from agent33.mcp_server.proxy_manager import ProxyManager
from agent33.mcp_server.proxy_models import ProxyServerConfig
from agent33.tools.base import ToolContext, ToolResult
from agent33.tools.registry import ToolRegistry
from agent33.tools.registry_entry import ToolRegistryEntry
from agent33.workflows.definition import WorkflowDefinition


class _SchemaTool:
    @property
    def name(self) -> str:
        return "shell"

    @property
    def description(self) -> str:
        return "Run a shell command."

    @property
    def parameters_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        }

    async def execute(self, params: dict[str, object], context: ToolContext) -> ToolResult:  # noqa: ARG002
        return ToolResult.ok(str(params))


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


def _make_bridge() -> MCPServiceBridge:
    agent_registry = AgentRegistry()
    agent_registry.register(
        AgentDefinition(
            name="implementer",
            agent_id="AGT-001",
            version="1.0.0",
            role=AgentRole.IMPLEMENTER,
            description="Writes production code.",
            capabilities=[AgentCapability.FILE_WRITE],
        )
    )

    tool_registry = ToolRegistry()
    tool = _SchemaTool()
    tool_registry.register_with_entry(
        tool,
        ToolRegistryEntry(
            tool_id="shell",
            name="shell",
            version="1.2.0",
            description="Run commands",
            owner="platform",
            parameters_schema={"type": "object", "properties": {"argv": {"type": "array"}}},
            result_schema={"type": "object", "properties": {"stdout": {"type": "string"}}},
        ),
    )

    workflow = WorkflowDefinition.model_validate(
        {
            "name": "release",
            "version": "1.0.0",
            "steps": [{"id": "build", "action": "run-command", "command": "echo ok"}],
        }
    )

    return MCPServiceBridge(
        agent_registry=agent_registry,
        tool_registry=tool_registry,
        workflow_registry={"release": workflow},
    )


def _make_bridge_with_proxy() -> MCPServiceBridge:
    bridge = _make_bridge()
    proxy_manager = ProxyManager()
    handle = ChildServerHandle(ProxyServerConfig(id="fs", command="echo", tool_prefix="fs"))
    handle.state = ChildServerState.HEALTHY
    handle.register_tools([ProxyToolDefinition(name="read_file", description="Read file")])
    proxy_manager._children["fs"] = handle
    bridge.proxy_manager = proxy_manager
    return bridge


class TestMCPResourceContract:
    async def test_list_resources_matches_documented_contract(self) -> None:
        from agent33.mcp_server.resources import handle_list_resources

        result = await handle_list_resources(_make_bridge())
        assert [entry["uri"] for entry in result] == [
            "agent33://agent-registry",
            "agent33://tool-catalog",
            "agent33://proxy-servers",
            "agent33://policy-pack",
            "agent33://pricing-catalog",
            "agent33://schema-index",
        ]

    async def test_list_resource_templates_matches_documented_contract(self) -> None:
        from agent33.mcp_server.resources import handle_list_resource_templates

        result = await handle_list_resource_templates(_make_bridge())
        assert [entry["uriTemplate"] for entry in result] == [
            "agent33://agents/{id}",
            "agent33://tools/{name}",
            "agent33://workflows/{id}",
        ]

    async def test_agent_registry_resource_returns_agent_catalog(self) -> None:
        from agent33.mcp_server.resources import handle_read_resource

        payload = json.loads(
            await handle_read_resource(_make_bridge(), "agent33://agent-registry")
        )
        assert payload["count"] == 1
        assert payload["agents"][0]["id"] == "AGT-001"
        assert payload["agents"][0]["name"] == "implementer"

    async def test_tool_catalog_resource_returns_schema_metadata(self) -> None:
        from agent33.mcp_server.resources import handle_read_resource

        payload = json.loads(await handle_read_resource(_make_bridge(), "agent33://tool-catalog"))
        assert payload["count"] == 1
        tool = payload["tools"][0]
        assert tool["name"] == "shell"
        assert tool["schema_source"] == "registry_entry"
        assert tool["has_parameters_schema"] is True
        assert tool["has_result_schema"] is True

    async def test_policy_pack_resource_serializes_effective_policy(self, monkeypatch) -> None:
        from agent33.mcp_server.resources import handle_read_resource

        monkeypatch.setattr("agent33.config.settings.connector_boundary_enabled", True)
        monkeypatch.setattr("agent33.config.settings.connector_policy_pack", "mcp-readonly")
        monkeypatch.setattr("agent33.config.settings.connector_circuit_breaker_enabled", True)
        monkeypatch.setattr("agent33.config.settings.connector_circuit_failure_threshold", 5)
        monkeypatch.setattr("agent33.config.settings.connector_circuit_recovery_seconds", 45.0)
        monkeypatch.setattr("agent33.config.settings.connector_circuit_half_open_successes", 2)
        monkeypatch.setattr(
            "agent33.config.settings.connector_circuit_max_recovery_seconds", 180.0
        )
        monkeypatch.setattr(
            "agent33.config.settings.connector_governance_blocked_connectors",
            "tool:web_fetch",
        )
        monkeypatch.setattr(
            "agent33.config.settings.connector_governance_blocked_operations",
            "resources/read",
        )

        payload = json.loads(await handle_read_resource(_make_bridge(), "agent33://policy-pack"))
        assert payload["configured_policy_pack"] == "mcp-readonly"
        assert "tools/call" in payload["effective_policy"]["blocked_operations"]
        assert "resources/read" in payload["effective_policy"]["blocked_operations"]
        assert "tool:web_fetch" in payload["effective_policy"]["blocked_connectors"]
        assert payload["logical_middleware_order"] == [
            "governance",
            "timeout",
            "retry",
            "circuit_breaker",
            "metrics",
        ]
        assert payload["active_middleware_order"] == [
            "governance",
            "timeout",
            "circuit_breaker",
            "metrics",
        ]
        assert payload["retry_policy"]["default_retry_attempts"] == 1
        assert payload["retry_policy"]["enabled_when_retry_attempts_gt_one"] is True
        assert payload["retry_policy"]["default_behavior"].startswith("no automatic retry")
        assert payload["retry_policy"]["middleware_position"] == 2
        assert payload["retry_policy"]["non_retryable_failures"] == [
            "governance_denied",
            "circuit_open",
        ]
        assert payload["circuit_breaker_policy"] == {
            "enabled": True,
            "failure_threshold": 5,
            "recovery_timeout_seconds": 45.0,
            "half_open_success_threshold": 2,
            "max_recovery_timeout_seconds": 180.0,
            "recovery_backoff": "progressive_exponential_capped",
            "middleware_position": 3,
        }

    async def test_schema_index_contains_agent_workflow_and_tool_schema_data(self) -> None:
        from agent33.mcp_server.resources import handle_read_resource

        payload = json.loads(await handle_read_resource(_make_bridge(), "agent33://schema-index"))
        assert "agent_definition_schema" in payload
        assert "workflow_definition_schema" in payload
        assert payload["tool_schema_index"]["count"] == 1
        assert payload["tool_schema_index"]["items"][0]["name"] == "shell"

    async def test_pricing_catalog_resource_serializes_pricing_and_heuristic_contract(
        self, monkeypatch
    ) -> None:
        from agent33.mcp_server.resources import handle_read_resource

        monkeypatch.setattr("agent33.config.settings.agent_effort_routing_enabled", True)
        monkeypatch.setattr("agent33.config.settings.agent_effort_default", "medium")
        monkeypatch.setattr("agent33.config.settings.heuristic_simple_max_chars", 144)
        monkeypatch.setattr("agent33.config.settings.heuristic_simple_max_words", 21)
        monkeypatch.setattr(
            "agent33.config.settings.agent_effort_heuristic_low_score_threshold", 1
        )
        monkeypatch.setattr(
            "agent33.config.settings.agent_effort_heuristic_high_score_threshold", 4
        )
        monkeypatch.setattr(
            "agent33.config.settings.agent_effort_heuristic_medium_payload_chars", 750
        )
        monkeypatch.setattr(
            "agent33.config.settings.agent_effort_heuristic_large_payload_chars", 1800
        )
        monkeypatch.setattr(
            "agent33.config.settings.agent_effort_heuristic_many_input_fields_threshold",
            8,
        )
        monkeypatch.setattr(
            "agent33.config.settings.agent_effort_heuristic_high_iteration_threshold", 12
        )
        monkeypatch.setattr("agent33.config.settings.agent_effort_low_model", "gpt-4.1-mini")
        monkeypatch.setattr("agent33.config.settings.agent_effort_medium_model", "")
        monkeypatch.setattr("agent33.config.settings.agent_effort_high_model", "gpt-4.1")
        monkeypatch.setattr("agent33.config.settings.agent_effort_low_token_multiplier", 0.5)
        monkeypatch.setattr("agent33.config.settings.agent_effort_medium_token_multiplier", 1.0)
        monkeypatch.setattr("agent33.config.settings.agent_effort_high_token_multiplier", 1.5)
        monkeypatch.setattr("agent33.config.settings.agent_effort_cost_per_1k_tokens", 0.25)

        payload = json.loads(
            await handle_read_resource(_make_bridge(), "agent33://pricing-catalog")
        )

        assert payload["entry_count"] >= 25
        assert payload["override_count"] == 0
        assert payload["catalog_snapshot_fetched_at"] is not None
        assert payload["cost_estimation_policy"] == {
            "prefers_per_model_catalog_when_provider_resolves": True,
            "flat_rate_fallback_cost_per_1k_tokens": 0.25,
            "unknown_model_behavior": (
                "estimated_cost is omitted when neither the catalog nor the flat-rate fallback "
                "can produce a value"
            ),
        }
        assert payload["heuristic_policy"] == {
            "enabled": True,
            "default_effort": "medium",
            "simple_message_fast_path": {"max_chars": 144, "max_words": 21},
            "score_thresholds": {"low": 1, "high": 4},
            "payload_thresholds": {"medium_chars": 750, "large_chars": 1800},
            "many_input_fields_threshold": 8,
            "high_iteration_threshold": 12,
            "model_overrides": {
                "low": "gpt-4.1-mini",
                "medium": None,
                "high": "gpt-4.1",
            },
            "token_multipliers": {"low": 0.5, "medium": 1.0, "high": 1.5},
        }

        gpt41 = next(
            entry
            for entry in payload["entries"]
            if entry["provider"] == "openai" and entry["model"] == "gpt-4.1"
        )
        assert gpt41["input_cost_per_million"] == "2"
        assert gpt41["output_cost_per_million"] == "8"
        assert gpt41["source"] == "official_docs_snapshot"
        assert gpt41["source_url"] == "https://openai.com/api/pricing/"
        assert gpt41["fetched_at"] is not None

    async def test_pricing_catalog_resource_uses_datetime_order_for_snapshot(self) -> None:
        from agent33.mcp_server.resources import handle_read_resource

        catalog = PricingCatalog()
        catalog.set_override(
            "openai",
            "gpt-4.1",
            PricingEntry(
                input_cost_per_million=Decimal("9"),
                output_cost_per_million=Decimal("19"),
                source=CostSource.USER_OVERRIDE,
                fetched_at=datetime.fromisoformat("2026-03-29T08:00:00+02:00"),
            ),
        )
        catalog.set_override(
            "openai",
            "gpt-4.1-mini",
            PricingEntry(
                input_cost_per_million=Decimal("1"),
                output_cost_per_million=Decimal("2"),
                source=CostSource.USER_OVERRIDE,
                fetched_at=datetime.fromisoformat("2026-03-29T07:30:00+00:00"),
            ),
        )

        with patch("agent33.mcp_server.resources.get_default_catalog", return_value=catalog):
            payload = json.loads(
                await handle_read_resource(_make_bridge(), "agent33://pricing-catalog")
            )

        assert payload["catalog_snapshot_fetched_at"] == "2026-03-29T07:30:00+00:00"

    async def test_agent_template_uses_agent_identifier(self) -> None:
        from agent33.mcp_server.resources import handle_read_resource

        payload = json.loads(
            await handle_read_resource(_make_bridge(), "agent33://agents/AGT-001")
        )
        assert payload["name"] == "implementer"
        assert payload["resolved_id"] == "AGT-001"

    async def test_workflow_template_reads_from_workflow_registry(self) -> None:
        from agent33.mcp_server.resources import handle_read_resource

        payload = json.loads(
            await handle_read_resource(_make_bridge(), "agent33://workflows/release")
        )
        assert payload["name"] == "release"
        assert payload["steps"][0]["id"] == "build"

    async def test_proxy_servers_resource_returns_proxy_fleet_data(self) -> None:
        from agent33.mcp_server.resources import handle_read_resource

        payload = json.loads(
            await handle_read_resource(_make_bridge_with_proxy(), "agent33://proxy-servers")
        )
        assert payload["total"] == 1
        assert payload["servers"][0]["id"] == "fs"
        assert payload["tools"][0]["name"] == "fs__read_file"


class TestResourceRegistration:
    async def test_register_resources_uses_single_canonical_handler_path(self) -> None:
        from agent33.mcp_server import resources as resources_mod

        server = _MockMCPServer()
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
            resources_mod.register_resources(server, _make_bridge())

        resources = await server.handlers["list_resources"]()
        templates = await server.handlers["list_resource_templates"]()
        payload = json.loads(await server.handlers["read_resource"]("agent33://tool-catalog"))

        assert [str(resource.uri) for resource in resources] == [
            "agent33://agent-registry",
            "agent33://tool-catalog",
            "agent33://proxy-servers",
            "agent33://policy-pack",
            "agent33://pricing-catalog",
            "agent33://schema-index",
        ]
        assert [str(template.uriTemplate) for template in templates] == [
            "agent33://agents/{id}",
            "agent33://tools/{name}",
            "agent33://workflows/{id}",
        ]
        assert payload["tools"][0]["name"] == "shell"
