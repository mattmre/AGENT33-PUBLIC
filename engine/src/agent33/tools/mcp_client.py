"""MCP Client integration for AGENT-33.

Provides abstractions to connect to remote or local Model Context Protocol (MCP) servers,
translate their tool schemas into AGENT-33 SchemaAwareTools, and execute them dynamically.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client

from agent33.config import settings
from agent33.connectors.boundary import (
    build_connector_boundary_executor,
    map_connector_exception,
)
from agent33.connectors.models import ConnectorRequest
from agent33.tools.base import SchemaAwareTool, ToolContext, ToolResult

logger = logging.getLogger(__name__)


class MCPToolAdapter(SchemaAwareTool):
    """Wraps a remote MCP tool so it behaves like a native AGENT-33 Tool."""

    def __init__(
        self,
        session: ClientSession,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        manager: MCPClientManager | None = None,
        policy_pack: str | None = None,
    ) -> None:
        self._session = session
        self._name = name
        self._description = description
        self._schema = input_schema
        self._manager = manager
        self._policy_pack = policy_pack

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return self._schema

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            param_keys = sorted(params.keys())
            logger.debug(
                "Executing MCP tool %s with %d argument(s): %s",
                self._name,
                len(param_keys),
                param_keys,
            )
            if self._manager is not None:
                result = await self._manager.call_tool(
                    session=self._session,
                    tool_name=self._name,
                    arguments=params,
                    connector_name=f"mcp:{self._name}",
                    policy_pack=self._policy_pack,
                )
            else:
                result = await self._session.call_tool(self._name, arguments=params)

            output = ""
            for item in getattr(result, "content", []):
                if hasattr(item, "text"):
                    output += item.text + "\n"

            if getattr(result, "isError", False):
                return ToolResult.fail(output.strip())

            return ToolResult.ok(output.strip())
        except Exception as e:
            logger.error(f"Failed to execute MCP tool {self._name}", exc_info=True)
            return ToolResult.fail(str(e))


class MCPClientManager:
    """Manages connections to multiple MCP servers and orchestrates their lifecycles."""

    def __init__(self) -> None:
        self._sessions: list[ClientSession] = []
        self._exit_stacks: list[contextlib.AsyncExitStack] = []

    async def call_tool(
        self,
        session: ClientSession,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        connector_name: str = "mcp:client",
        policy_pack: str | None = None,
        timeout_seconds: float | None = None,
    ) -> Any:
        """Call an MCP tool with optional connector boundary enforcement."""

        async def _perform_tool_call(_request: ConnectorRequest) -> Any:
            return await session.call_tool(tool_name, arguments=arguments)

        resolved_timeout_seconds = (
            float(timeout_seconds)
            if timeout_seconds is not None
            else float(getattr(settings, "mcp_timeout_seconds", 30.0))
        )
        boundary_executor = build_connector_boundary_executor(
            default_timeout_seconds=resolved_timeout_seconds,
            retry_attempts=1,
            policy_pack=policy_pack,
        )
        if boundary_executor is None:
            return await _perform_tool_call(
                ConnectorRequest(connector=connector_name, operation="tools/call")
            )

        request = ConnectorRequest(
            connector=connector_name,
            operation="tools/call",
            payload={"name": tool_name, "arguments": arguments},
            metadata={"timeout_seconds": resolved_timeout_seconds},
        )
        try:
            return await boundary_executor.execute(request, _perform_tool_call)
        except Exception as exc:
            raise map_connector_exception(exc, connector_name, "tools/call") from exc

    async def connect_stdio(
        self, command: str, args: list[str], env: dict[str, str] | None = None
    ) -> ClientSession:
        """Connect to a local command-line application exposing an MCP STDIO server."""
        server_params = StdioServerParameters(command=command, args=args, env=env)
        stack = contextlib.AsyncExitStack()
        self._exit_stacks.append(stack)

        try:
            # We assume asyncio environment
            read_stream, write_stream = await stack.enter_async_context(
                stdio_client(server_params)
            )
            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            await session.initialize()
            self._sessions.append(session)
            logger.info(f"Connected to MCP STDIO Server: {command} {' '.join(args)}")
            return session
        except Exception as e:
            logger.error(f"Failed to connect to MCP STDIO server: {command}", exc_info=True)
            await stack.aclose()
            raise e

    async def connect_sse(self, url: str) -> ClientSession:
        """Connect to a remote MCP server via HTTP Server-Sent Events (SSE)."""
        stack = contextlib.AsyncExitStack()
        self._exit_stacks.append(stack)

        try:
            read_stream, write_stream = await stack.enter_async_context(sse_client(url))
            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            await session.initialize()
            self._sessions.append(session)
            logger.info(f"Connected to MCP SSE Server: {url}")
            return session
        except Exception as e:
            logger.error(f"Failed to connect to MCP SSE server: {url}", exc_info=True)
            await stack.aclose()
            raise e

    async def load_tools_from_session(self, session: ClientSession) -> list[MCPToolAdapter]:
        """Query the remote server for available tools and map them to AGENT-33 Adapters."""
        try:
            response = await session.list_tools()
            adapters = []
            for tool in getattr(response, "tools", []):
                adapters.append(
                    MCPToolAdapter(
                        session=session,
                        name=tool.name,
                        description=tool.description,
                        input_schema=tool.inputSchema,
                        manager=self,
                    )
                )
            logger.debug(f"Loaded {len(adapters)} tools from MCP session")
            return adapters
        except Exception:
            logger.error("Failed to load tools from MCP session", exc_info=True)
            return []

    async def close_all(self) -> None:
        """Cleanly shutdown all MCP connections."""
        for stack in self._exit_stacks:
            try:
                await stack.aclose()
            except Exception as e:
                logger.warning(f"Error closing MCP connection: {e}")

        self._sessions.clear()
        self._exit_stacks.clear()
        logger.info("Closed all MCP connections")
