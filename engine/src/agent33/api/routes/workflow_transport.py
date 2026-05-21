"""Transport negotiation, config, and stats endpoints for workflow streaming."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from fastapi import APIRouter, Request

from agent33.security.permissions import require_scope

if TYPE_CHECKING:
    from agent33.workflows.transport import WorkflowTransportManager

router = APIRouter(prefix="/v1/workflows/transport", tags=["workflows"])


@router.get("/config", dependencies=[require_scope("workflows:read")])
async def get_transport_config(request: Request) -> dict[str, Any]:
    """Return the current workflow transport configuration."""
    manager = getattr(request.app.state, "workflow_transport_manager", None)
    if manager is None:
        return {
            "preferred": "auto",
            "ws_ping_interval": 30.0,
            "ws_ping_timeout": 10.0,
            "sse_retry_ms": 3000,
            "max_reconnect_attempts": 5,
        }
    config = manager.config
    return {
        "preferred": config.preferred.value,
        "ws_ping_interval": config.ws_ping_interval,
        "ws_ping_timeout": config.ws_ping_timeout,
        "sse_retry_ms": config.sse_retry_ms,
        "max_reconnect_attempts": config.max_reconnect_attempts,
    }


@router.get("/stats", dependencies=[require_scope("workflows:read")])
async def get_transport_stats(request: Request) -> dict[str, Any]:
    """Return live transport statistics for workflow event streaming."""
    manager = getattr(request.app.state, "workflow_transport_manager", None)
    if manager is None:
        return {
            "transport_preferred": "auto",
            "active_ws_connections": 0,
            "active_ws_bridge_subscribers": 0,
            "active_ws_bridge_runs": 0,
            "active_ws_manager_connections": 0,
            "active_sse_streams": 0,
            "total_ws_served": 0,
            "total_sse_served": 0,
            "total_served": 0,
            "config": {
                "preferred": "auto",
                "ws_ping_interval": 30.0,
                "ws_ping_timeout": 10.0,
                "sse_retry_ms": 3000,
                "max_reconnect_attempts": 5,
            },
            "uptime_seconds": 0.0,
        }
    transport_mgr = cast("WorkflowTransportManager", manager)
    return await transport_mgr.get_transport_stats()


@router.get("/negotiate", dependencies=[require_scope("workflows:read")])
async def negotiate_transport(request: Request) -> dict[str, Any]:
    """Perform transport negotiation based on the current request headers.

    Clients can call this endpoint to discover which transport the server
    would select for them before initiating a streaming connection.
    """
    manager = getattr(request.app.state, "workflow_transport_manager", None)
    if manager is None:
        return {
            "requested": "auto",
            "resolved": "sse",
            "fallback_reason": "Transport manager not initialized",
        }
    transport_mgr = cast("WorkflowTransportManager", manager)
    headers = dict(request.headers)
    negotiation = transport_mgr.negotiate(headers)
    result: dict[str, Any] = negotiation.model_dump()
    return result
