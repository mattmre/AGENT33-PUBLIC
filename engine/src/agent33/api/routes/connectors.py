"""Connector monitoring API routes (Phase 32 UX) and messaging registration."""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from agent33.connectors.models import (
    CircuitBreakerSnapshot,
    CircuitEvent,
    ConnectorHealthSummary,
    ConnectorMetricsSummary,
    ConnectorStatus,
)
from agent33.security.permissions import require_scope

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/connectors", tags=["connectors"])

# ---------------------------------------------------------------------------
# Messaging adapter registration models
# ---------------------------------------------------------------------------

SUPPORTED_MESSAGING_ADAPTERS = {"telegram", "discord", "slack", "whatsapp"}


class MessagingConnectRequest(BaseModel):
    adapter: str = Field(..., description="Adapter name: telegram, discord, slack, whatsapp")
    config: dict[str, Any] = Field(..., description="Adapter-specific config (token, etc.)")


class MessagingConnectResponse(BaseModel):
    adapter: str
    status: str  # "ok" | "degraded" | "unavailable" | "pending"
    detail: str


def _get_proxy_manager(request: Request) -> Any:
    """Return the proxy manager from app.state, or None."""
    return getattr(request.app.state, "proxy_manager", None)


def _get_connector_metrics(request: Request) -> Any:
    """Return the ConnectorMetricsCollector from app.state, or None."""
    return getattr(request.app.state, "connector_metrics", None)


def _build_circuit_snapshot(breaker: Any) -> CircuitBreakerSnapshot:
    """Return a normalized circuit-breaker snapshot for API responses."""
    if hasattr(breaker, "snapshot"):
        return CircuitBreakerSnapshot(**breaker.snapshot())

    recovery_timeout = getattr(breaker, "recovery_timeout_seconds", 30.0)
    effective_timeout = getattr(
        breaker,
        "effective_recovery_timeout",
        recovery_timeout,
    )
    return CircuitBreakerSnapshot(
        state=getattr(getattr(breaker, "state", None), "value", "unknown"),
        consecutive_failures=getattr(breaker, "consecutive_failures", 0),
        total_trips=getattr(breaker, "total_trips", 0),
        last_trip_at=getattr(breaker, "last_trip_at", None),
        failure_threshold=getattr(breaker, "failure_threshold", 3),
        recovery_timeout_seconds=recovery_timeout,
        half_open_success_threshold=getattr(breaker, "half_open_success_threshold", 2),
        max_recovery_timeout_seconds=getattr(
            breaker,
            "max_recovery_timeout_seconds",
            recovery_timeout,
        ),
        effective_recovery_timeout_seconds=effective_timeout,
        cooldown_remaining_seconds=max(
            0.0,
            float(
                getattr(
                    breaker,
                    "cooldown_remaining_seconds",
                    0.0,
                )
            ),
        ),
    )


def _build_proxy_statuses(proxy_manager: Any) -> list[ConnectorStatus]:
    """Build ConnectorStatus entries from the MCP proxy fleet."""
    statuses: list[ConnectorStatus] = []
    if proxy_manager is None:
        return statuses
    for summary in proxy_manager.list_servers():
        circuit_snap = None
        server_handle = proxy_manager.get_server(summary["id"])
        if server_handle is not None and hasattr(server_handle, "circuit_breaker"):
            cb = server_handle.circuit_breaker
            circuit_snap = _build_circuit_snapshot(cb)
        statuses.append(
            ConnectorStatus(
                connector_id=summary["id"],
                name=summary.get("name", summary["id"]),
                connector_type="mcp_proxy",
                state=summary.get("state", "unknown"),
                circuit=circuit_snap,
            )
        )
    return statuses


def _build_boundary_statuses(connector_metrics: Any, proxy_ids: set[str]) -> list[ConnectorStatus]:
    """Build ConnectorStatus entries from boundary-level metrics."""
    statuses: list[ConnectorStatus] = []
    if connector_metrics is None:
        return statuses
    for cid in connector_metrics.list_known_connectors():
        if cid in proxy_ids:
            continue
        raw = connector_metrics.get_connector_metrics(cid)
        statuses.append(
            ConnectorStatus(
                connector_id=cid,
                name=cid,
                connector_type="boundary",
                state="active" if raw["total_calls"] > 0 else "idle",
                metrics=ConnectorMetricsSummary(**raw),
            )
        )
    return statuses


def _compute_health_summary(
    statuses: list[ConnectorStatus],
) -> ConnectorHealthSummary:
    """Derive fleet-level counts from connector statuses."""
    total = len(statuses)
    healthy = 0
    degraded = 0
    open_circuit = 0
    stopped = 0
    for s in statuses:
        if s.state in {"healthy", "active", "closed"}:
            healthy += 1
        elif s.state == "degraded":
            degraded += 1
        elif s.state == "stopped":
            stopped += 1
        elif s.state in {"open", "unhealthy", "cooldown"} or (
            s.circuit is not None and s.circuit.state == "open"
        ):
            open_circuit += 1
        else:
            # idle or unknown -- count as healthy
            healthy += 1
    return ConnectorHealthSummary(
        total=total,
        healthy=healthy,
        degraded=degraded,
        open_circuit=open_circuit,
        stopped=stopped,
    )


@router.get("")
async def list_connectors(
    request: Request,
) -> dict[str, Any]:
    """List all known connectors with current state, circuit snapshot, and metrics."""
    proxy_manager = _get_proxy_manager(request)
    connector_metrics = _get_connector_metrics(request)

    proxy_statuses = _build_proxy_statuses(proxy_manager)
    proxy_ids = {s.connector_id for s in proxy_statuses}

    # Attach metrics to proxy statuses when available
    if connector_metrics is not None:
        for ps in proxy_statuses:
            raw = connector_metrics.get_connector_metrics(ps.connector_id)
            if raw["total_calls"] > 0:
                ps.metrics = ConnectorMetricsSummary(**raw)

    boundary_statuses = _build_boundary_statuses(connector_metrics, proxy_ids)
    all_statuses = proxy_statuses + boundary_statuses
    summary = _compute_health_summary(all_statuses)

    return {
        "connectors": [s.model_dump() for s in all_statuses],
        "health": summary.model_dump(),
    }


@router.get("/health")
async def connector_health(request: Request) -> dict[str, Any]:
    """Return just the fleet-level ConnectorHealthSummary."""
    proxy_manager = _get_proxy_manager(request)
    connector_metrics = _get_connector_metrics(request)

    proxy_statuses = _build_proxy_statuses(proxy_manager)
    proxy_ids = {s.connector_id for s in proxy_statuses}
    boundary_statuses = _build_boundary_statuses(connector_metrics, proxy_ids)
    all_statuses = proxy_statuses + boundary_statuses
    summary = _compute_health_summary(all_statuses)

    return summary.model_dump()


@router.get("/{connector_id}")
async def get_connector(request: Request, connector_id: str) -> dict[str, Any]:
    """Return a single connector's detail with full metrics."""
    proxy_manager = _get_proxy_manager(request)
    connector_metrics = _get_connector_metrics(request)

    # Check proxy fleet first
    if proxy_manager is not None:
        handle = proxy_manager.get_server(connector_id)
        if handle is not None:
            summary = handle.status_summary()
            circuit_snap = None
            if hasattr(handle, "circuit_breaker"):
                cb = handle.circuit_breaker
                circuit_snap = _build_circuit_snapshot(cb)
            metrics = None
            if connector_metrics is not None:
                raw = connector_metrics.get_connector_metrics(connector_id)
                if raw["total_calls"] > 0:
                    metrics = ConnectorMetricsSummary(**raw)
            status = ConnectorStatus(
                connector_id=connector_id,
                name=summary.get("name", connector_id),
                connector_type="mcp_proxy",
                state=summary.get("state", "unknown"),
                circuit=circuit_snap,
                metrics=metrics,
            )
            return status.model_dump()

    # Check boundary metrics
    if connector_metrics is not None:
        known = connector_metrics.list_known_connectors()
        if connector_id in known:
            raw = connector_metrics.get_connector_metrics(connector_id)
            status = ConnectorStatus(
                connector_id=connector_id,
                name=connector_id,
                connector_type="boundary",
                state="active" if raw["total_calls"] > 0 else "idle",
                metrics=ConnectorMetricsSummary(**raw),
            )
            return status.model_dump()

    raise HTTPException(status_code=404, detail=f"Connector '{connector_id}' not found")


@router.get("/{connector_id}/events")
async def get_connector_events(
    request: Request,
    connector_id: str,
    limit: int = 20,
) -> dict[str, Any]:
    """Return circuit breaker event history for a connector."""
    connector_metrics = _get_connector_metrics(request)
    if connector_metrics is None:
        return {"connector_id": connector_id, "events": []}

    raw_events = connector_metrics.get_circuit_events(connector_id, limit=limit)
    events = [
        CircuitEvent(
            connector_id=e["connector_id"],
            old_state=e["old_state"],
            new_state=e["new_state"],
            timestamp=e["timestamp"],
        ).model_dump()
        for e in raw_events
    ]
    return {"connector_id": connector_id, "events": events}


# ---------------------------------------------------------------------------
# Messaging adapter registration and health
# ---------------------------------------------------------------------------


def _build_messaging_adapter(adapter_name: str, config: dict[str, Any]) -> Any:
    """Instantiate the named messaging adapter from the supplied config dict.

    Returns the adapter instance, or raises ``HTTPException(400)`` if required
    config keys are missing.
    """
    if adapter_name == "telegram":
        from agent33.messaging.telegram import TelegramAdapter

        token = config.get("token") or config.get("bot_token")
        if not token:
            raise HTTPException(
                status_code=400,
                detail="telegram adapter requires config.token (bot token)",
            )
        return TelegramAdapter(token=str(token))

    if adapter_name == "discord":
        from agent33.messaging.discord import DiscordAdapter

        bot_token = config.get("token") or config.get("bot_token")
        public_key = config.get("public_key", "")
        if not bot_token:
            raise HTTPException(
                status_code=400,
                detail="discord adapter requires config.token (bot token)",
            )
        return DiscordAdapter(bot_token=str(bot_token), public_key=str(public_key))

    if adapter_name == "slack":
        from agent33.messaging.slack import SlackAdapter

        bot_token = config.get("token") or config.get("bot_token")
        signing_secret = config.get("signing_secret", "")
        if not bot_token:
            raise HTTPException(
                status_code=400,
                detail="slack adapter requires config.token (bot token)",
            )
        return SlackAdapter(bot_token=str(bot_token), signing_secret=str(signing_secret))

    if adapter_name == "whatsapp":
        from agent33.messaging.whatsapp import WhatsAppAdapter

        access_token = config.get("token") or config.get("access_token")
        phone_number_id = config.get("phone_number_id", "")
        verify_token = config.get("verify_token", "")
        app_secret = config.get("app_secret", "")
        if not access_token:
            raise HTTPException(
                status_code=400,
                detail="whatsapp adapter requires config.token (access token)",
            )
        return WhatsAppAdapter(
            access_token=str(access_token),
            phone_number_id=str(phone_number_id),
            verify_token=str(verify_token),
            app_secret=str(app_secret),
        )

    # Should be unreachable — caller validates adapter name first.
    raise HTTPException(status_code=400, detail=f"Unknown adapter '{adapter_name}'")


@router.post(
    "/messaging/register",
    response_model=MessagingConnectResponse,
    dependencies=[require_scope("admin")],
    summary="Register and probe a messaging adapter",
)
async def register_messaging_adapter(
    body: MessagingConnectRequest,
    request: Request,
) -> MessagingConnectResponse:
    """Instantiate the named messaging adapter, run its health check, and return status.

    This is the backend that the *Connect* buttons in the frontend Integrations
    panel call. The adapter is not persisted across restarts unless the caller
    also writes the config to the .env file via ``/v1/config/apply``.
    """
    if body.adapter not in SUPPORTED_MESSAGING_ADAPTERS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown adapter '{body.adapter}'. "
                f"Supported: {sorted(SUPPORTED_MESSAGING_ADAPTERS)}"
            ),
        )

    # Build the adapter (validates required config fields).
    adapter = _build_messaging_adapter(body.adapter, body.config)

    # Start the adapter so health_check() has a live HTTP client.
    try:
        await adapter.start()
    except Exception as exc:
        logger.warning(
            "messaging_adapter_start_failed: adapter=%s error=%s",
            body.adapter,
            exc,
        )
        return MessagingConnectResponse(
            adapter=body.adapter,
            status="unavailable",
            detail=f"Adapter start failed: {exc}",
        )

    try:
        result = await adapter.health_check()
    except Exception as exc:
        logger.exception("messaging_adapter_health_check_error: adapter=%s", body.adapter)
        return MessagingConnectResponse(
            adapter=body.adapter,
            status="unavailable",
            detail=f"Health check raised: {exc}",
        )
    finally:
        # Always stop the transient adapter — we don't hold live adapters in state.
        with contextlib.suppress(Exception):
            await adapter.stop()

    # Store the adapter name on nats_bus.adapters if available, as a registration marker.
    nats_bus = getattr(request.app.state, "nats_bus", None)
    if nats_bus is not None:
        registered = getattr(nats_bus, "adapters", None)
        if registered is None:
            with contextlib.suppress(Exception):
                nats_bus.adapters = {body.adapter: True}
        elif isinstance(registered, dict):
            registered[body.adapter] = True

    return MessagingConnectResponse(
        adapter=body.adapter,
        status=result.status,
        detail=result.detail or f"Health check status: {result.status}",
    )


@router.get(
    "/messaging/status",
    dependencies=[require_scope("admin")],
    summary="List registered messaging adapters",
)
async def list_messaging_adapter_status(request: Request) -> dict[str, Any]:
    """Return the set of messaging adapter names that have been registered this session."""
    nats_bus = getattr(request.app.state, "nats_bus", None)
    adapters: dict[str, Any] = {}
    if nats_bus is not None:
        registered = getattr(nats_bus, "adapters", None)
        if isinstance(registered, dict):
            adapters = registered
    return {
        "adapters": [{"name": name, "status": "registered"} for name in adapters],
        "supported": sorted(SUPPORTED_MESSAGING_ADAPTERS),
    }
