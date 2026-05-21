"""Thin MCP auth helpers backed by the shared permissions system."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent33.security.permissions import check_permission

if TYPE_CHECKING:
    from collections.abc import Iterable

TOOL_SCOPES: dict[str, str] = {
    "list_agents": "agents:read",
    "invoke_agent": "agents:invoke",
    "search_memory": "agents:read",
    "list_tools": "agents:read",
    "discover_tools": "tools:execute",
    "execute_tool": "tools:execute",
    "list_skills": "agents:read",
    "discover_skills": "agents:read",
    "resolve_workflow": "workflows:read",
    "get_system_status": "agents:read",
    # Phase 45: proxy admin tools
    "proxy_list_servers": "agents:read",
    "proxy_add_server": "admin",
    "proxy_remove_server": "admin",
}

RESOURCE_SCOPES: dict[str, str] = {
    "agent33://agent-registry": "agents:read",
    "agent33://tool-catalog": "agents:read",
    "agent33://policy-pack": "component-security:read",
    "agent33://pricing-catalog": "component-security:read",
    "agent33://schema-index": "agents:read",
    "agent33://agents/": "agents:read",
    "agent33://tools/": "agents:read",
    "agent33://workflows/": "workflows:read",
    # Phase 45: proxy resource
    "agent33://proxy-servers": "agents:read",
}


def get_server_request(server: Any) -> Any:
    """Return the active request from the MCP server context, if present."""
    try:
        request_context = getattr(server, "request_context", None)
    except LookupError:
        return None

    try:
        return getattr(request_context, "request", None)
    except LookupError:
        return None


def get_authenticated_scopes(server: Any) -> list[str]:
    """Return authenticated scopes from the active MCP request context."""
    request = get_server_request(server)
    user = getattr(getattr(request, "state", None), "user", None)
    if user is None:
        return []
    return list(getattr(user, "scopes", []))


def get_required_scope_for_tool(tool_name: str, *, tool_separator: str = "__") -> str | None:
    """Return the scope required to invoke an MCP tool.

    Proxy tools (containing the configured separator) that are not explicitly scoped
    default to ``tools:execute`` rather than ``None``, so they are
    routable through the proxy dispatch path.
    """
    scope = TOOL_SCOPES.get(tool_name)
    if scope is not None:
        return scope
    # Phase 45: proxy tools use tools:execute by default
    if tool_separator and tool_separator in tool_name:
        return "tools:execute"
    return None


def get_required_scope_for_resource(uri: str) -> str | None:
    """Return the scope required to read an MCP resource."""
    exact_scope = RESOURCE_SCOPES.get(uri)
    if exact_scope is not None:
        return exact_scope

    if "{" in uri:
        uri = uri.split("{", 1)[0]

    for prefix, scope in RESOURCE_SCOPES.items():
        if prefix.endswith("/") and uri.startswith(prefix):
            return scope

    return None


def enforce_tool_scope(server: Any, tool_name: str) -> None:
    """Raise when the current request lacks scope for an MCP tool."""
    required_scope = get_required_scope_for_tool(
        tool_name,
        tool_separator=_get_proxy_tool_separator(server),
    )
    if required_scope is None:
        raise PermissionError(f"MCP tool '{tool_name}' is not allowed")
    _enforce_scope(server, required_scope)


def enforce_resource_scope(server: Any, uri: str) -> None:
    """Raise when the current request lacks scope for an MCP resource."""
    required_scope = get_required_scope_for_resource(uri)
    if required_scope is None:
        raise PermissionError(f"MCP resource '{uri}' is not allowed")
    _enforce_scope(server, required_scope)


def filter_allowed_tools(server: Any, tool_names: Iterable[str]) -> list[str]:
    """Return only tool names visible to the current request."""
    visible: list[str] = []
    for tool_name in tool_names:
        try:
            enforce_tool_scope(server, tool_name)
        except PermissionError:
            continue
        visible.append(tool_name)
    return visible


def enforce_registry_tool_access(server: Any, bridge: Any, tool_name: str) -> None:
    """Raise when a requested registry tool should not be executable."""
    _enforce_scope(server, "tools:execute")
    if not tool_name:
        raise PermissionError("Missing required MCP tool name")

    tool_registry = getattr(bridge, "tool_registry", None)
    if tool_registry is None or tool_registry.get(tool_name) is None:
        raise PermissionError(f"MCP registry tool '{tool_name}' is not allowed")

    entry = getattr(tool_registry, "get_entry", lambda *_: None)(tool_name)
    status = getattr(getattr(entry, "status", None), "value", None)
    if status == "blocked":
        raise PermissionError(f"MCP registry tool '{tool_name}' is blocked")


def _enforce_scope(server: Any, required_scope: str) -> None:
    request = get_server_request(server)
    user = getattr(getattr(request, "state", None), "user", None)
    if user is None:
        raise PermissionError("MCP request is not authenticated")

    if not check_permission(required_scope, list(getattr(user, "scopes", []))):
        raise PermissionError(f"Missing required scope: {required_scope}")


def _get_proxy_tool_separator(server: Any) -> str:
    separator = getattr(server, "proxy_tool_separator", "__")
    if isinstance(separator, str) and separator:
        return separator
    return "__"
