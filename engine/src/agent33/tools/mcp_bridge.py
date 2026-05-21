"""MCP (Model Context Protocol) interop bridge.

Connects AGENT-33's tool registry to external MCP servers, discovering
their tools at startup and exposing them as native :class:`SchemaAwareTool`
instances.  Communication uses JSON-RPC-style HTTP POSTs over ``httpx``.
"""

from __future__ import annotations

import ipaddress
import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from agent33.connectors.boundary import build_connector_boundary_executor
from agent33.connectors.models import ConnectorRequest
from agent33.tools.base import ToolContext, ToolResult
from agent33.tools.schema import validate_params

if TYPE_CHECKING:
    from agent33.connectors.executor import ConnectorExecutor

logger = logging.getLogger(__name__)

_BLOCKED_NETWORKS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


def _validate_mcp_url(url: str) -> str:
    """Validate URL shape and block obvious SSRF targets."""
    normalized = url.rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Unsupported MCP URL scheme: {parsed.scheme!r}")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("MCP URL must include a hostname")
    if hostname.lower() == "localhost":
        raise ValueError("MCP URL host 'localhost' is blocked by SSRF policy")
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        return normalized
    if any(addr in net for net in _BLOCKED_NETWORKS):
        raise ValueError(f"MCP URL host '{hostname}' is blocked by SSRF policy")
    return normalized


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class MCPToolSpec(BaseModel):
    """Specification of a single tool advertised by an MCP server."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Server connection
# ---------------------------------------------------------------------------


class MCPServerConnection:
    """Manages the connection to a single MCP server.

    Uses JSON-RPC-style HTTP POSTs to communicate.  The ``connect()``
    method discovers available tools and caches them locally.
    """

    def __init__(
        self,
        name: str,
        url: str,
        timeout: float = 30.0,
        boundary_executor: ConnectorExecutor | None = None,
        policy_pack: str | None = None,
    ) -> None:
        self._name = name
        self._url = _validate_mcp_url(url)
        self._timeout = timeout
        self._policy_pack = policy_pack
        self._tools: list[MCPToolSpec] = []
        self._connected = False
        self._client: httpx.AsyncClient | None = None
        self._boundary_executor: ConnectorExecutor | None
        if boundary_executor is not None:
            self._boundary_executor = boundary_executor
        else:
            self._boundary_executor = self._build_boundary_executor()

    @property
    def name(self) -> str:
        return self._name

    @property
    def url(self) -> str:
        return self._url

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def tools(self) -> list[MCPToolSpec]:
        return list(self._tools)

    async def connect(self) -> None:
        """Connect and discover tools from the MCP server."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._connected = False
        self._tools = []
        self._client = httpx.AsyncClient(timeout=self._timeout)
        try:
            self._tools = await self.list_tools()
        except Exception:
            await self._client.aclose()
            self._client = None
            self._connected = False
            self._tools = []
            raise
        self._connected = True
        logger.info(
            "Connected to MCP server %s (%s): %d tools discovered",
            self._name,
            self._url,
            len(self._tools),
        )

    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._connected = False
        self._tools = []
        logger.info("Disconnected from MCP server %s", self._name)

    async def list_tools(self) -> list[MCPToolSpec]:
        """Retrieve the list of tools from the MCP server."""
        response = await self._rpc("tools/list", {})
        tools_data = response.get("tools", [])
        return [
            MCPToolSpec(
                name=t.get("name", ""),
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", t.get("input_schema", {})),
            )
            for t in tools_data
            if isinstance(t, dict)
        ]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Invoke a tool on the MCP server and return the result."""
        response = await self._rpc(
            "tools/call",
            {"name": tool_name, "arguments": arguments},
        )
        return response.get("content", response)

    async def health_check(self) -> bool:
        """Check if the MCP server is reachable."""
        try:
            await self._rpc("ping", {})
            return True
        except Exception:
            logger.debug("Health check failed for MCP server %s", self._name)
            return False

    async def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC-style POST to the MCP server."""
        if self._boundary_executor is None:
            return await self._perform_rpc(method=method, params=params)
        request = ConnectorRequest(
            connector=f"mcp:{self._name}",
            operation=method,
            payload={"params": params},
            metadata={"url": self._url},
        )
        result = await self._boundary_executor.execute(
            request,
            self._execute_boundary_rpc,
        )
        if not isinstance(result, dict):
            raise RuntimeError(f"MCP RPC returned non-object JSON from {self._name}")
        return result

    async def _execute_boundary_rpc(self, request: ConnectorRequest) -> dict[str, Any]:
        params = request.payload.get("params")
        if not isinstance(params, dict):
            raise RuntimeError("Connector request payload missing 'params' object")
        return await self._perform_rpc(method=request.operation, params=params)

    async def _perform_rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }
        resp = await self._client.post(self._url, json=payload)
        resp.raise_for_status()
        try:
            body = resp.json()
        except ValueError as exc:
            raise RuntimeError(f"MCP RPC returned invalid JSON from {self._name}") from exc
        if not isinstance(body, dict):
            raise RuntimeError(f"MCP RPC returned non-object JSON from {self._name}")

        if "error" in body:
            error = body["error"]
            msg = error.get("message", str(error)) if isinstance(error, dict) else str(error)
            raise RuntimeError(f"MCP RPC error from {self._name}: {msg}")

        result: dict[str, Any] = body.get("result", body)
        return result

    def _build_boundary_executor(self) -> ConnectorExecutor | None:
        return build_connector_boundary_executor(
            default_timeout_seconds=self._timeout,
            retry_attempts=1,
            policy_pack=self._policy_pack,
        )


# ---------------------------------------------------------------------------
# Tool adapter (SchemaAwareTool)
# ---------------------------------------------------------------------------


class MCPToolAdapter:
    """Wraps an :class:`MCPToolSpec` and :class:`MCPServerConnection` as a
    native AGENT-33 tool implementing the ``SchemaAwareTool`` interface.
    """

    def __init__(self, spec: MCPToolSpec, connection: MCPServerConnection) -> None:
        self._spec = spec
        self._connection = connection

    @property
    def name(self) -> str:
        return self._spec.name

    @property
    def description(self) -> str:
        return self._spec.description

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return self._spec.input_schema

    async def execute(
        self,
        params: dict[str, Any],
        context: ToolContext,  # noqa: ARG002
    ) -> ToolResult:
        """Execute the tool via the MCP server connection."""
        try:
            result = await self._connection.call_tool(self._spec.name, params)
            if isinstance(result, str):
                return ToolResult.ok(result)
            # Extract text from content blocks (MCP convention)
            if isinstance(result, list):
                texts = []
                for item in result:
                    if isinstance(item, dict) and "text" in item:
                        texts.append(item["text"])
                    else:
                        texts.append(str(item))
                return ToolResult.ok("\n".join(texts))
            return ToolResult.ok(str(result))
        except Exception as exc:
            return ToolResult.fail(f"MCP tool '{self._spec.name}' failed: {exc}")

    async def validated_execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        """Validate params against the schema, then execute."""
        if self._spec.input_schema:
            vr = validate_params(params, self._spec.input_schema)
            if not vr.valid:
                return ToolResult.fail(f"Parameter validation failed: {'; '.join(vr.errors)}")
        return await self.execute(params, context)


# ---------------------------------------------------------------------------
# Bridge (top-level manager)
# ---------------------------------------------------------------------------


class MCPBridge:
    """Top-level manager for MCP server connections.

    Connects to MCP servers, discovers their tools, and registers them
    in the AGENT-33 tool registry.
    """

    def __init__(self, tool_registry: Any | None = None) -> None:
        self._tool_registry = tool_registry
        self._servers: dict[str, MCPServerConnection] = {}
        self._adapters: list[MCPToolAdapter] = []

    def add_server(
        self,
        name: str,
        url: str,
        timeout: float = 30.0,
        policy_pack: str | None = None,
    ) -> None:
        """Register an MCP server to connect to during initialization."""
        self._servers[name] = MCPServerConnection(
            name=name,
            url=url,
            timeout=timeout,
            policy_pack=policy_pack,
        )
        logger.info("MCP server queued: %s (%s)", name, url)

    async def initialize(self) -> None:
        """Connect to all registered servers and discover tools.

        Discovered tools are wrapped as :class:`MCPToolAdapter` instances
        and registered in the tool registry (if one is provided).
        """
        self._adapters.clear()
        for name, conn in self._servers.items():
            try:
                await conn.connect()
                for spec in conn.tools:
                    adapter = MCPToolAdapter(spec=spec, connection=conn)
                    self._adapters.append(adapter)
                    if self._tool_registry is not None:
                        self._tool_registry.register(adapter)
                    logger.info("Registered MCP tool: %s (from %s)", spec.name, name)
            except Exception:
                logger.exception("Failed to connect to MCP server %s", name)

    async def shutdown(self) -> None:
        """Disconnect from all MCP servers."""
        for conn in self._servers.values():
            try:
                await conn.disconnect()
            except Exception:
                logger.exception("Error disconnecting MCP server %s", conn.name)
        self._adapters.clear()

    def get_mcp_tools(self) -> list[MCPToolAdapter]:
        """Return all discovered MCP tool adapters."""
        return list(self._adapters)
