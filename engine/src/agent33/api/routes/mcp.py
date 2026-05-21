"""MCP (Model Context Protocol) server endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette import status
from starlette.responses import StreamingResponse

from agent33.security.permissions import require_scope

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/mcp", tags=["mcp-server"])

MCP_MESSAGES_ENDPOINT = "/v1/mcp/messages"
MCP_UNAVAILABLE_REASON = "MCP server or SSE transport is not initialized"


def _mcp_availability(bridge: Any, mcp_server: Any, transport: Any) -> dict[str, Any]:
    sdk_available = mcp_server is not None
    transport_available = transport is not None
    available = sdk_available and transport_available
    state = "available" if available else "degraded"
    reason = None if available else MCP_UNAVAILABLE_REASON
    if bridge is None:
        state = "unavailable"
        reason = "MCP bridge is not initialized"

    payload: dict[str, Any] = {
        "available": available,
        "state": state,
        "mcp_sdk_installed": sdk_available,
        "transport_available": transport_available,
    }
    if reason is not None:
        payload["reason"] = reason
    return payload


def _format_sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, sort_keys=True)}\n\n"


class _SSEBridgeStream:
    """Async iterator that runs the MCP SSE bridge and yields no body chunks."""

    def __init__(self, request: Request, transport: Any, mcp_server: Any) -> None:
        self._request = request
        self._transport = transport
        self._mcp_server = mcp_server
        self._done = False

    def __aiter__(self) -> _SSEBridgeStream:
        return self

    async def __anext__(self) -> str:
        if self._done:
            raise StopAsyncIteration
        self._done = True
        try:
            send = _get_request_send(self._request)
            async with self._transport.connect_sse(
                self._request.scope,
                self._request.receive,
                send,
            ) as (read_stream, write_stream):
                await self._mcp_server.run(
                    read_stream,
                    write_stream,
                    self._mcp_server.create_initialization_options(),
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("MCP SSE stream error")
            raise
        raise StopAsyncIteration


def require_authenticated_user(request: Request) -> Any:
    """Ensure the current request is authenticated."""
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user


def _get_request_send(request: Request) -> Any:
    send = getattr(request, "_send", None)
    if send is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MCP transport send channel unavailable",
        )
    return send


@router.get("/sse", dependencies=[Depends(require_authenticated_user)])
async def mcp_sse(request: Request) -> StreamingResponse:
    """SSE endpoint for MCP protocol."""
    mcp_server = getattr(request.app.state, "mcp_server", None)
    transport = getattr(request.app.state, "mcp_transport", None)

    if mcp_server is None or transport is None:

        async def stub_stream() -> AsyncGenerator[str, None]:
            yield _format_sse("endpoint", {"messages_endpoint": MCP_MESSAGES_ENDPOINT})
            yield _format_sse(
                "status",
                _mcp_availability(
                    getattr(request.app.state, "mcp_bridge", None),
                    mcp_server,
                    transport,
                ),
            )

        return StreamingResponse(
            stub_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    return StreamingResponse(
        _SSEBridgeStream(request, transport, mcp_server),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/messages", dependencies=[Depends(require_authenticated_user)])
async def mcp_messages(request: Request) -> dict[str, Any]:
    """Handle MCP protocol messages."""
    transport = getattr(request.app.state, "mcp_transport", None)
    if transport is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "unavailable",
                "reason": "MCP transport not initialized",
                "messages_endpoint": MCP_MESSAGES_ENDPOINT,
            },
        )

    try:
        body = await request.body()
        await transport.handle_post_message(
            request.scope,
            request.receive,
            _get_request_send(request),
            body,
        )
        return {"status": "processed"}
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("MCP message error")
        raise HTTPException(500, f"MCP message error: {exc}") from exc


@router.get("/status", dependencies=[require_scope("agents:read")])
async def mcp_status(request: Request) -> dict[str, Any]:
    """MCP server status."""
    bridge = getattr(request.app.state, "mcp_bridge", None)
    mcp_server = getattr(request.app.state, "mcp_server", None)
    transport = getattr(request.app.state, "mcp_transport", None)

    availability = _mcp_availability(bridge, mcp_server, transport)

    if bridge is None:
        return availability

    return {**availability, **bridge.get_system_status()}
