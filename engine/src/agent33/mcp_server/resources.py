"""MCP resource handlers for the documented Agent-33 resource contract."""

from __future__ import annotations

import importlib
import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar, cast

from agent33.config import settings
from agent33.connectors import boundary as connector_boundary
from agent33.llm.pricing import get_default_catalog
from agent33.tools.schema import get_tool_schema

if TYPE_CHECKING:
    from agent33.mcp_server.bridge import MCPServiceBridge

_HAS_MCP = False
Resource: type[Any] | None = None
ResourceTemplate: type[Any] | None = None
try:
    _mcp_types = importlib.import_module("mcp.types")
except ImportError:
    pass
else:  # pragma: no branch - optional dependency bootstrap
    Resource = cast("type[Any] | None", getattr(_mcp_types, "Resource", None))
    ResourceTemplate = cast("type[Any] | None", getattr(_mcp_types, "ResourceTemplate", None))
    _HAS_MCP = Resource is not None and ResourceTemplate is not None

_HandlerT = TypeVar("_HandlerT", bound=Callable[..., Any])

STATIC_RESOURCES: list[dict[str, str]] = [
    {
        "uri": "agent33://agent-registry",
        "name": "Agent Registry",
        "description": "Catalog of registered agents.",
        "mimeType": "application/json",
    },
    {
        "uri": "agent33://tool-catalog",
        "name": "Tool Catalog",
        "description": "Catalog of registered tools and schema availability.",
        "mimeType": "application/json",
    },
    {
        "uri": "agent33://proxy-servers",
        "name": "Proxy Servers",
        "description": "Configured MCP proxy servers and aggregated tool inventory.",
        "mimeType": "application/json",
    },
    {
        "uri": "agent33://policy-pack",
        "name": "Policy Pack",
        "description": "Configured and effective connector-boundary policy data.",
        "mimeType": "application/json",
    },
    {
        "uri": "agent33://pricing-catalog",
        "name": "Pricing Catalog",
        "description": "Auditable per-model pricing provenance and live effort-routing settings.",
        "mimeType": "application/json",
    },
    {
        "uri": "agent33://schema-index",
        "name": "Schema Index",
        "description": "Core schema metadata for agents, workflows, and tools.",
        "mimeType": "application/json",
    },
]

RESOURCE_TEMPLATES: list[dict[str, str]] = [
    {
        "uriTemplate": "agent33://agents/{id}",
        "name": "Agent Definition",
        "description": "Definition for a specific registered agent.",
        "mimeType": "application/json",
    },
    {
        "uriTemplate": "agent33://tools/{name}",
        "name": "Tool Definition",
        "description": "Details and schema metadata for a specific tool.",
        "mimeType": "application/json",
    },
    {
        "uriTemplate": "agent33://workflows/{id}",
        "name": "Workflow Definition",
        "description": "Definition for a specific registered workflow.",
        "mimeType": "application/json",
    },
]


async def handle_list_resources(bridge: MCPServiceBridge) -> list[dict[str, str]]:  # noqa: ARG001
    """Return the static MCP resource definitions."""
    return STATIC_RESOURCES


async def handle_list_resource_templates(
    bridge: MCPServiceBridge,  # noqa: ARG001
) -> list[dict[str, str]]:
    """Return the templated MCP resource definitions."""
    return RESOURCE_TEMPLATES


async def handle_read_resource(bridge: MCPServiceBridge, uri: str) -> str:
    """Read a resource by URI and return its JSON payload."""
    payload: dict[str, Any]

    if uri == "agent33://agent-registry":
        payload = _read_agent_registry(bridge)
    elif uri == "agent33://tool-catalog":
        payload = _read_tool_catalog(bridge)
    elif uri == "agent33://proxy-servers":
        payload = _read_proxy_servers(bridge)
    elif uri == "agent33://policy-pack":
        payload = _read_policy_pack()
    elif uri == "agent33://pricing-catalog":
        payload = _read_pricing_catalog()
    elif uri == "agent33://schema-index":
        payload = _read_schema_index(bridge)
    elif uri.startswith("agent33://agents/"):
        payload = _read_agent_detail(bridge, uri.removeprefix("agent33://agents/"))
    elif uri.startswith("agent33://tools/"):
        payload = _read_tool_detail(bridge, uri.removeprefix("agent33://tools/"))
    elif uri.startswith("agent33://workflows/"):
        payload = _read_workflow_detail(bridge, uri.removeprefix("agent33://workflows/"))
    else:
        payload = {"error": f"Unknown resource URI: {uri}"}

    return json.dumps(payload, indent=2, default=str)


def register_resources(
    server: Any,
    bridge: MCPServiceBridge,
    *,
    before_list: Callable[[str], None] | None = None,
    before_read: Callable[[str], None] | None = None,
) -> None:
    """Register MCP resource handlers on a live MCP server."""
    if not _HAS_MCP:
        return

    resource_cls = Resource
    template_cls = ResourceTemplate
    if resource_cls is None or template_cls is None:
        return

    async def list_resources() -> list[Any]:
        return [
            resource_cls(
                uri=resource["uri"],
                name=resource["name"],
                description=resource.get("description", ""),
                mimeType=resource.get("mimeType", "application/json"),
            )
            for resource in await handle_list_resources(bridge)
            if before_list is None or _allow_listed_identifier(before_list, resource["uri"])
        ]

    _register_handler(server.list_resources(), list_resources)

    async def list_resource_templates() -> list[Any]:
        return [
            template_cls(
                uriTemplate=resource["uriTemplate"],
                name=resource["name"],
                description=resource.get("description", ""),
                mimeType=resource.get("mimeType", "application/json"),
            )
            for resource in await handle_list_resource_templates(bridge)
            if before_list is None
            or _allow_listed_identifier(before_list, resource["uriTemplate"])
        ]

    _register_handler(server.list_resource_templates(), list_resource_templates)

    async def read_resource(uri: Any) -> str:
        uri_str = str(uri)
        if before_read is not None:
            before_read(uri_str)
        return await handle_read_resource(bridge, uri_str)

    _register_handler(server.read_resource(), read_resource)


def _read_agent_registry(bridge: MCPServiceBridge) -> dict[str, Any]:
    if bridge.agent_registry is None:
        return {"error": "Agent registry not available"}

    agents = bridge.agent_registry.list_all()
    return {
        "count": len(agents),
        "agents": [_serialize_agent_summary(agent) for agent in agents],
    }


def _read_tool_catalog(bridge: MCPServiceBridge) -> dict[str, Any]:
    if bridge.tool_registry is None:
        return {"error": "Tool registry not available"}

    tools = sorted(bridge.tool_registry.list_all(), key=lambda tool: tool.name)
    return {
        "count": len(tools),
        "tools": [_serialize_tool_summary(bridge, tool.name) for tool in tools],
    }


def _read_proxy_servers(bridge: MCPServiceBridge) -> dict[str, Any]:
    if bridge.proxy_manager is None:
        return {"error": "Proxy manager not available"}

    return {
        "servers": bridge.proxy_manager.list_servers(),
        "tools": bridge.proxy_manager.list_aggregated_tools(),
        **bridge.proxy_manager.health_summary(),
    }


def _read_policy_pack() -> dict[str, Any]:
    configured_pack = settings.connector_policy_pack
    pack_blocked_connectors, pack_blocked_operations = connector_boundary.get_policy_pack(
        configured_pack
    )
    configured_blocked_connectors = _parse_csv_set(
        settings.connector_governance_blocked_connectors
    )
    configured_blocked_operations = _parse_csv_set(
        settings.connector_governance_blocked_operations
    )
    logical_middleware_order = [
        "governance",
        "timeout",
        "retry",
        "circuit_breaker",
        "metrics",
    ]
    active_middleware_order = ["governance", "timeout"]
    if settings.connector_circuit_breaker_enabled:
        active_middleware_order.append("circuit_breaker")
    active_middleware_order.append("metrics")

    return {
        "connector_boundary_enabled": settings.connector_boundary_enabled,
        "configured_policy_pack": configured_pack,
        "available_policy_packs": sorted(getattr(connector_boundary, "_POLICY_PACKS", {}).keys()),
        "configured_blocklists": {
            "blocked_connectors": sorted(configured_blocked_connectors),
            "blocked_operations": sorted(configured_blocked_operations),
        },
        "pack_defaults": {
            "blocked_connectors": sorted(pack_blocked_connectors),
            "blocked_operations": sorted(pack_blocked_operations),
        },
        "logical_middleware_order": logical_middleware_order,
        "active_middleware_order": active_middleware_order,
        "retry_policy": {
            "default_retry_attempts": 1,
            "enabled_when_retry_attempts_gt_one": True,
            "default_behavior": "no automatic retry unless a caller opts into retry_attempts > 1",
            "non_retryable_failures": [
                "governance_denied",
                "circuit_open",
            ],
            "middleware_position": logical_middleware_order.index("retry"),
        },
        "circuit_breaker_policy": {
            "enabled": settings.connector_circuit_breaker_enabled,
            "failure_threshold": settings.connector_circuit_failure_threshold,
            "recovery_timeout_seconds": settings.connector_circuit_recovery_seconds,
            "half_open_success_threshold": settings.connector_circuit_half_open_successes,
            "max_recovery_timeout_seconds": settings.connector_circuit_max_recovery_seconds,
            "recovery_backoff": "progressive_exponential_capped",
            "middleware_position": logical_middleware_order.index("circuit_breaker"),
        },
        "effective_policy": {
            "blocked_connectors": sorted(
                pack_blocked_connectors.union(configured_blocked_connectors)
            ),
            "blocked_operations": sorted(
                pack_blocked_operations.union(configured_blocked_operations)
            ),
        },
    }


def _read_pricing_catalog() -> dict[str, Any]:
    catalog = get_default_catalog()
    entries: list[dict[str, Any]] = []
    latest_snapshot = None
    override_count = 0

    for provider, model, entry in catalog.list_effective_entries():
        fetched_at = entry.fetched_at.isoformat() if entry.fetched_at is not None else None
        if entry.fetched_at is not None and (
            latest_snapshot is None or entry.fetched_at > latest_snapshot
        ):
            latest_snapshot = entry.fetched_at
        if entry.source.value == "user_override":
            override_count += 1
        entries.append(
            {
                "provider": provider,
                "model": model,
                "input_cost_per_million": str(entry.input_cost_per_million),
                "output_cost_per_million": str(entry.output_cost_per_million),
                "cache_read_cost_per_million": str(entry.cache_read_cost_per_million),
                "cache_write_cost_per_million": str(entry.cache_write_cost_per_million),
                "source": entry.source.value,
                "source_url": entry.source_url,
                "fetched_at": fetched_at,
            }
        )

    return {
        "entry_count": len(entries),
        "override_count": override_count,
        "catalog_snapshot_fetched_at": (
            latest_snapshot.isoformat() if latest_snapshot is not None else None
        ),
        "entries": entries,
        "cost_estimation_policy": {
            "prefers_per_model_catalog_when_provider_resolves": True,
            "flat_rate_fallback_cost_per_1k_tokens": settings.agent_effort_cost_per_1k_tokens,
            "unknown_model_behavior": (
                "estimated_cost is omitted when neither the catalog nor the flat-rate fallback "
                "can produce a value"
            ),
        },
        "heuristic_policy": {
            "enabled": settings.agent_effort_routing_enabled,
            "default_effort": settings.agent_effort_default,
            "simple_message_fast_path": {
                "max_chars": settings.heuristic_simple_max_chars,
                "max_words": settings.heuristic_simple_max_words,
            },
            "score_thresholds": {
                "low": settings.agent_effort_heuristic_low_score_threshold,
                "high": settings.agent_effort_heuristic_high_score_threshold,
            },
            "payload_thresholds": {
                "medium_chars": settings.agent_effort_heuristic_medium_payload_chars,
                "large_chars": settings.agent_effort_heuristic_large_payload_chars,
            },
            "many_input_fields_threshold": (
                settings.agent_effort_heuristic_many_input_fields_threshold
            ),
            "high_iteration_threshold": settings.agent_effort_heuristic_high_iteration_threshold,
            "model_overrides": {
                "low": settings.agent_effort_low_model or None,
                "medium": settings.agent_effort_medium_model or None,
                "high": settings.agent_effort_high_model or None,
            },
            "token_multipliers": {
                "low": settings.agent_effort_low_token_multiplier,
                "medium": settings.agent_effort_medium_token_multiplier,
                "high": settings.agent_effort_high_token_multiplier,
            },
        },
    }


def _read_schema_index(bridge: MCPServiceBridge) -> dict[str, Any]:
    from agent33.agents.definition import AgentDefinition
    from agent33.workflows.definition import WorkflowDefinition

    tool_items: list[dict[str, Any]] = []
    if bridge.tool_registry is not None:
        for tool in sorted(bridge.tool_registry.list_all(), key=lambda item: item.name):
            tool_items.append(_serialize_tool_schema_index_item(bridge, tool.name))

    return {
        "agent_definition_schema": AgentDefinition.model_json_schema(),
        "workflow_definition_schema": WorkflowDefinition.model_json_schema(),
        "tool_schema_index": {
            "count": len(tool_items),
            "items": tool_items,
        },
    }


def _read_agent_detail(bridge: MCPServiceBridge, identifier: str) -> dict[str, Any]:
    agent = bridge.get_agent(identifier)
    if agent is None:
        return {"error": f"Agent '{identifier}' not found"}

    data = _model_dump_dict(agent)
    data["resolved_id"] = data.get("agent_id") or data.get("name")
    return data


def _read_tool_detail(bridge: MCPServiceBridge, name: str) -> dict[str, Any]:
    if bridge.tool_registry is None:
        return {"error": "Tool registry not available"}

    tool = bridge.tool_registry.get(name)
    if tool is None:
        return {"error": f"Tool '{name}' not found"}

    return _serialize_tool_summary(bridge, name, include_schemas=True)


def _read_workflow_detail(bridge: MCPServiceBridge, identifier: str) -> dict[str, Any]:
    workflow = bridge.get_workflow(identifier)
    if workflow is None:
        return {"error": f"Workflow '{identifier}' not found"}
    return _model_dump_dict(workflow)


def _serialize_agent_summary(agent: Any) -> dict[str, Any]:
    capabilities = []
    for capability in getattr(agent, "capabilities", []) or []:
        capabilities.append(getattr(capability, "value", str(capability)))

    return {
        "id": getattr(agent, "agent_id", None) or agent.name,
        "name": agent.name,
        "agent_id": getattr(agent, "agent_id", None),
        "role": getattr(getattr(agent, "role", None), "value", getattr(agent, "role", None)),
        "description": getattr(agent, "description", ""),
        "status": getattr(getattr(agent, "status", None), "value", getattr(agent, "status", None)),
        "autonomy_level": getattr(
            getattr(agent, "autonomy_level", None),
            "value",
            getattr(agent, "autonomy_level", None),
        ),
        "capabilities": capabilities,
    }


def _serialize_tool_summary(
    bridge: MCPServiceBridge,
    name: str,
    *,
    include_schemas: bool = False,
) -> dict[str, Any]:
    assert bridge.tool_registry is not None

    tool = bridge.tool_registry.get(name)
    entry = bridge.tool_registry.get_entry(name)
    schema = get_tool_schema(tool, entry) if tool is not None else None

    payload: dict[str, Any] = {
        "name": name,
        "description": getattr(tool, "description", ""),
        "version": getattr(entry, "version", None),
        "status": getattr(getattr(entry, "status", None), "value", None),
        "tags": list(getattr(entry, "tags", []) or []),
        "schema_source": _get_tool_schema_source(tool, entry),
        "has_parameters_schema": schema is not None,
        "has_result_schema": bool(entry and entry.result_schema),
    }
    if entry is not None:
        payload["owner"] = entry.owner
        payload["provenance"] = _model_dump_dict(entry.provenance)
        payload["scope"] = _model_dump_dict(entry.scope)
    if include_schemas:
        payload["parameters_schema"] = schema
        payload["result_schema"] = entry.result_schema if entry is not None else None
    return payload


def _serialize_tool_schema_index_item(bridge: MCPServiceBridge, name: str) -> dict[str, Any]:
    tool_detail = _serialize_tool_summary(bridge, name, include_schemas=True)
    return {
        "name": tool_detail["name"],
        "schema_source": tool_detail["schema_source"],
        "has_parameters_schema": tool_detail["has_parameters_schema"],
        "has_result_schema": tool_detail["has_result_schema"],
        "parameters_schema": tool_detail["parameters_schema"],
        "result_schema": tool_detail["result_schema"],
    }


def _get_tool_schema_source(tool: Any, entry: Any) -> str | None:
    if entry is not None and getattr(entry, "parameters_schema", None):
        return "registry_entry"
    if tool is not None and hasattr(tool, "parameters_schema"):
        try:
            if tool.parameters_schema:
                return "tool"
        except Exception:
            return None
    return None


def _parse_csv(value: str) -> list[str]:
    return sorted(item.strip() for item in value.split(",") if item.strip())


def _parse_csv_set(value: str) -> frozenset[str]:
    return frozenset(item.strip() for item in value.split(",") if item.strip())


def _register_handler(decorator: Any, handler: _HandlerT) -> _HandlerT:
    typed_decorator = cast("Callable[[_HandlerT], _HandlerT]", decorator)
    return typed_decorator(handler)


def _allow_listed_identifier(checker: Callable[[str], None], identifier: str) -> bool:
    try:
        checker(identifier)
    except PermissionError:
        return False
    return True


def _model_dump_dict(model: Any) -> dict[str, Any]:
    raw = model.model_dump(mode="json")
    if not isinstance(raw, dict):
        return {"value": raw}
    return {str(key): value for key, value in raw.items()}
