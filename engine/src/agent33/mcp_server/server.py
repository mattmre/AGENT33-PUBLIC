"""MCP server setup and handler registration."""

from __future__ import annotations

import importlib
import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar, cast

from agent33.mcp_server.auth import (
    enforce_registry_tool_access,
    enforce_resource_scope,
    enforce_tool_scope,
    filter_allowed_tools,
    get_server_request,
)
from agent33.mcp_server.resources import register_resources
from agent33.tools.base import ToolContext

if TYPE_CHECKING:
    from agent33.mcp_server.bridge import MCPServiceBridge

logger = logging.getLogger(__name__)

_HAS_MCP = False
Server: type[Any] | None = None
TextContent: type[Any] | None = None
Tool: type[Any] | None = None
try:
    _mcp_server_module = importlib.import_module("mcp.server")
    _mcp_types_module = importlib.import_module("mcp.types")
except ImportError as exc:
    logger.warning("mcp_sdk_import_failed: %s", exc, exc_info=True)
else:  # pragma: no branch - optional dependency bootstrap
    Server = cast("type[Any] | None", getattr(_mcp_server_module, "Server", None))
    TextContent = cast("type[Any] | None", getattr(_mcp_types_module, "TextContent", None))
    Tool = cast("type[Any] | None", getattr(_mcp_types_module, "Tool", None))
    _HAS_MCP = Server is not None and TextContent is not None and Tool is not None

_HandlerT = TypeVar("_HandlerT", bound=Callable[..., Any])
_MCP_TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "list_agents",
        "description": "List all registered agents",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "invoke_agent",
        "description": "Invoke an agent with a message",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_name": {
                    "type": "string",
                    "description": "Name of the agent",
                },
                "message": {
                    "type": "string",
                    "description": "Message to send",
                },
                "model": {
                    "type": "string",
                    "description": "Model override (optional)",
                },
            },
            "required": ["agent_name", "message"],
        },
    },
    {
        "name": "search_memory",
        "description": "Search the memory/knowledge base",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_tools",
        "description": "List registered tools",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "discover_tools",
        "description": "Discover relevant runtime tools for a task",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Task or search query",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of matches",
                    "default": 10,
                    "minimum": 1,
                },
                "activate": {
                    "type": "boolean",
                    "description": (
                        "Activate matched tools for the current session "
                        "when dynamic mode is enabled"
                    ),
                    "default": True,
                },
                "activation_limit": {
                    "type": "integer",
                    "description": "Maximum number of matches to activate",
                    "default": 3,
                    "minimum": 1,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "execute_tool",
        "description": "Execute a registered tool",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "Tool name",
                },
                "arguments": {
                    "type": "object",
                    "description": "Tool arguments",
                },
            },
            "required": ["tool_name"],
        },
    },
    {
        "name": "list_skills",
        "description": "List registered skills",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "discover_skills",
        "description": "Discover relevant skills for a task",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Task or search query",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of matches",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "resolve_workflow",
        "description": "Resolve a workflow or template for a task",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Task or search query",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of matches",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_system_status",
        "description": "Get AGENT-33 system status",
        "inputSchema": {"type": "object", "properties": {}},
    },
)


def create_mcp_server(bridge: MCPServiceBridge) -> Any:
    """Create and configure the MCP server with tool and resource handlers."""
    if not _HAS_MCP:
        logger.warning("MCP SDK not installed, MCP server disabled")
        return None

    server_cls = Server
    tool_cls = Tool
    text_content_cls = TextContent
    if server_cls is None or tool_cls is None or text_content_cls is None:
        logger.warning("MCP SDK classes unavailable, MCP server disabled")
        return None

    server = server_cls("agent33-core")
    proxy_manager = getattr(bridge, "proxy_manager", None)
    server.proxy_tool_separator = (
        proxy_manager.tool_separator if proxy_manager is not None else "__"
    )

    async def list_tools() -> list[Any]:
        mcp_tools = list(_MCP_TOOL_DEFINITIONS)
        proxy_tools = proxy_manager.list_aggregated_tools() if proxy_manager is not None else []
        allowed = set(
            filter_allowed_tools(
                server,
                [tool["name"] for tool in mcp_tools] + [tool["name"] for tool in proxy_tools],
            )
        )
        return [tool_cls(**tool) for tool in mcp_tools if tool["name"] in allowed] + [
            tool_cls(
                name=tool["name"],
                description=tool.get("description", ""),
                inputSchema=tool.get("inputSchema", {}),
            )
            for tool in proxy_tools
            if tool["name"] in allowed
        ]

    _register_handler(server.list_tools(), list_tools)

    async def call_tool(name: str, arguments: dict[str, Any] | None = None) -> list[Any]:
        from agent33.mcp_server import tools as mcp_tools

        enforce_tool_scope(server, name)

        args = arguments or {}
        result: Any

        if name == "list_agents":
            result = await mcp_tools.handle_list_agents(bridge)
        elif name == "invoke_agent":
            result = await mcp_tools.handle_invoke_agent(
                bridge,
                agent_name=args.get("agent_name", ""),
                message=args.get("message", ""),
                model=args.get("model"),
            )
        elif name == "search_memory":
            result = await mcp_tools.handle_search_memory(
                bridge,
                query=args.get("query", ""),
                top_k=args.get("top_k", 5),
            )
        elif name == "list_tools":
            result = await mcp_tools.handle_list_tools(bridge, context=_build_tool_context(server))
        elif name == "discover_tools":
            result = await mcp_tools.handle_discover_tools(
                bridge,
                query=args.get("query", ""),
                limit=args.get("limit", 10),
                activate=args.get("activate", True),
                activation_limit=args.get("activation_limit", 3),
                context=_build_tool_context(server),
            )
        elif name == "execute_tool":
            enforce_registry_tool_access(server, bridge, str(args.get("tool_name", "")))
            result = await mcp_tools.handle_execute_tool(
                bridge,
                tool_name=args.get("tool_name", ""),
                arguments=args.get("arguments"),
                context=_build_tool_context(server),
            )
        elif name == "list_skills":
            result = await mcp_tools.handle_list_skills(bridge)
        elif name == "discover_skills":
            from agent33.security.permissions import check_permission

            context = _build_tool_context(server)
            tenant_id = (
                None
                if check_permission("admin", context.user_scopes)
                else (context.tenant_id or None)
            )
            result = await mcp_tools.handle_discover_skills(
                bridge,
                query=args.get("query", ""),
                limit=args.get("limit", 10),
                tenant_id=tenant_id,
            )
        elif name == "resolve_workflow":
            result = await mcp_tools.handle_resolve_workflow(
                bridge,
                query=args.get("query", ""),
                limit=args.get("limit", 10),
                context=_build_tool_context(server),
            )
        elif name == "get_system_status":
            result = await mcp_tools.handle_get_system_status(bridge)
        elif proxy_manager is not None and proxy_manager.resolve_server_for_tool(name):
            result = await proxy_manager.call_proxy_tool(name, args)
        else:
            raise PermissionError(f"MCP tool '{name}' is not allowed")

        return [text_content_cls(type="text", text=json.dumps(result, default=str))]

    _register_handler(server.call_tool(), call_tool)

    register_resources(
        server,
        bridge,
        before_list=lambda uri: enforce_resource_scope(server, uri),
        before_read=lambda uri: enforce_resource_scope(server, uri),
    )

    return server


def _build_tool_context(server: Any) -> ToolContext:
    request = get_server_request(server)
    user = getattr(getattr(request, "state", None), "user", None)
    if user is None:
        return ToolContext()

    headers = getattr(request, "headers", {})
    session_id = ""
    for header_name in ("x-agent-session-id", "x-session-id"):
        candidate = headers.get(header_name, "") if hasattr(headers, "get") else ""
        if str(candidate).strip():
            session_id = str(candidate).strip()
            break

    return ToolContext(
        user_scopes=list(getattr(user, "scopes", [])),
        requested_by=getattr(user, "sub", ""),
        tenant_id=getattr(user, "tenant_id", ""),
        session_id=session_id,
    )


def _register_handler(decorator: Any, handler: _HandlerT) -> _HandlerT:
    typed_decorator = cast("Callable[[_HandlerT], _HandlerT]", decorator)
    return typed_decorator(handler)
