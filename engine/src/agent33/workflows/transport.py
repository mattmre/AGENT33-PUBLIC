"""WebSocket-first transport with SSE fallback for workflow event streaming.

Provides transport negotiation, a WebSocket event bridge for fan-out delivery,
and unified transport statistics.  Integrates with the existing
:class:`~agent33.workflows.ws_manager.WorkflowWSManager` infrastructure without
replacing it.
"""

from __future__ import annotations

import asyncio
import time
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import structlog
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from agent33.workflows.events import WorkflowEvent
    from agent33.workflows.ws_manager import WorkflowWSManager

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Transport type enum
# ---------------------------------------------------------------------------


class TransportType(StrEnum):
    """Transport protocols available for workflow event streaming."""

    WEBSOCKET = "websocket"
    SSE = "sse"
    AUTO = "auto"


# ---------------------------------------------------------------------------
# Negotiation result
# ---------------------------------------------------------------------------


class TransportNegotiation(BaseModel):
    """Outcome of a transport negotiation handshake."""

    requested: TransportType
    resolved: TransportType
    fallback_reason: str | None = None


# ---------------------------------------------------------------------------
# Transport configuration
# ---------------------------------------------------------------------------


class TransportConfig(BaseModel):
    """Tuning knobs for the workflow transport layer."""

    preferred: TransportType = TransportType.AUTO
    ws_ping_interval: float = Field(default=30.0, ge=1.0)
    ws_ping_timeout: float = Field(default=10.0, ge=1.0)
    sse_retry_ms: int = Field(default=3000, ge=100)
    max_reconnect_attempts: int = Field(default=5, ge=0)


# ---------------------------------------------------------------------------
# WebSocket event bridge
# ---------------------------------------------------------------------------


class WebSocketEventBridge:
    """Fan-out delivery bridge for WebSocket subscribers on a per-run basis.

    Each ``run_id`` maintains an independent set of connected WebSocket
    objects.  :meth:`broadcast` delivers a serialised event to every
    subscriber for a given run.
    """

    def __init__(self) -> None:
        self._subscriptions: dict[str, set[Any]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, run_id: str, websocket: Any) -> None:
        """Register *websocket* as a subscriber for *run_id*."""
        async with self._lock:
            self._subscriptions.setdefault(run_id, set()).add(websocket)
        logger.debug("ws_bridge_subscribed", run_id=run_id)

    async def unsubscribe(self, run_id: str, websocket: Any) -> None:
        """Remove *websocket* from the subscriber set for *run_id*."""
        async with self._lock:
            subscribers = self._subscriptions.get(run_id)
            if subscribers is not None:
                subscribers.discard(websocket)
                if not subscribers:
                    del self._subscriptions[run_id]
        logger.debug("ws_bridge_unsubscribed", run_id=run_id)

    async def broadcast(self, run_id: str, event: dict[str, Any]) -> None:
        """Send *event* as JSON text to every WebSocket subscriber for *run_id*.

        Dead connections are silently removed.
        """
        import json

        payload = json.dumps(event)

        async with self._lock:
            subscribers = list(self._subscriptions.get(run_id, set()))

        if not subscribers:
            return

        dead: list[Any] = []
        for ws in subscribers:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
                logger.debug("ws_bridge_send_failed", run_id=run_id, exc_info=True)

        if dead:
            async with self._lock:
                subscriber_set = self._subscriptions.get(run_id)
                if subscriber_set is not None:
                    for ws in dead:
                        subscriber_set.discard(ws)
                    if not subscriber_set:
                        del self._subscriptions[run_id]

    async def subscriber_count(self, run_id: str) -> int:
        """Return the number of active subscribers for *run_id*."""
        async with self._lock:
            return len(self._subscriptions.get(run_id, set()))

    async def total_subscribers(self) -> int:
        """Return the total number of WebSocket subscribers across all runs."""
        async with self._lock:
            return sum(len(subs) for subs in self._subscriptions.values())

    async def active_runs(self) -> int:
        """Return the number of runs with at least one subscriber."""
        async with self._lock:
            return len(self._subscriptions)


# ---------------------------------------------------------------------------
# Transport manager
# ---------------------------------------------------------------------------


class WorkflowTransportManager:
    """Unified transport manager for WebSocket-first streaming with SSE fallback.

    Wraps the existing :class:`WorkflowWSManager` and adds transport
    negotiation, an independent :class:`WebSocketEventBridge`, and
    statistics tracking.
    """

    def __init__(
        self,
        config: TransportConfig | None = None,
        ws_manager: WorkflowWSManager | None = None,
    ) -> None:
        self._config = config or TransportConfig()
        self._ws_manager = ws_manager
        self._bridge = WebSocketEventBridge()
        self._stats_lock = asyncio.Lock()
        self._total_ws_served: int = 0
        self._total_sse_served: int = 0
        self._created_at: float = time.time()

    # -- properties ---------------------------------------------------------

    @property
    def config(self) -> TransportConfig:
        return self._config

    @property
    def bridge(self) -> WebSocketEventBridge:
        return self._bridge

    # -- negotiation --------------------------------------------------------

    def negotiate(self, request_headers: dict[str, str]) -> TransportNegotiation:
        """Decide which transport to use based on client headers and config.

        When *preferred* is ``AUTO``, the method checks for a WebSocket
        ``Upgrade`` header.  If present, WebSocket is selected; otherwise SSE
        is used as the fallback.

        When *preferred* is explicitly ``SSE`` or ``WEBSOCKET``, the preferred
        value is returned directly (the caller is responsible for verifying
        that the client actually supports the selected transport).
        """
        preferred = self._config.preferred

        if preferred == TransportType.SSE:
            return TransportNegotiation(
                requested=TransportType.SSE,
                resolved=TransportType.SSE,
            )

        if preferred == TransportType.WEBSOCKET:
            return TransportNegotiation(
                requested=TransportType.WEBSOCKET,
                resolved=TransportType.WEBSOCKET,
            )

        # AUTO: inspect headers
        upgrade_header = request_headers.get("upgrade", "").lower()
        if upgrade_header == "websocket":
            return TransportNegotiation(
                requested=TransportType.AUTO,
                resolved=TransportType.WEBSOCKET,
            )

        return TransportNegotiation(
            requested=TransportType.AUTO,
            resolved=TransportType.SSE,
            fallback_reason="No WebSocket Upgrade header present",
        )

    # -- WebSocket handler factory ------------------------------------------

    def create_ws_handler(self, run_id: str) -> Any:
        """Return an async handler that bridges a WebSocket to workflow events.

        The returned coroutine accepts a ``WebSocket`` and runs the
        receive loop until disconnect.  It delegates to the
        :class:`WebSocketEventBridge` for subscription management.
        """
        bridge = self._bridge
        manager = self

        async def _ws_handler(websocket: Any) -> None:
            await bridge.subscribe(run_id, websocket)
            async with manager._stats_lock:
                manager._total_ws_served += 1
            try:
                while True:
                    await websocket.receive_text()
            except Exception:
                pass
            finally:
                await bridge.unsubscribe(run_id, websocket)

        return _ws_handler

    # -- SSE handler factory ------------------------------------------------

    async def create_sse_handler(
        self,
        run_id: str,
        last_event_id: str | None = None,
    ) -> AsyncIterator[str]:
        """Return an async iterator that yields SSE-formatted event frames.

        If *last_event_id* is provided and the underlying manager has replay
        capability, missed events are replayed before switching to the live
        queue.
        """
        if self._ws_manager is None:
            return

        async with self._stats_lock:
            self._total_sse_served += 1

        queue, replay_events = await self._ws_manager.subscribe_sse_with_replay_if_allowed(
            run_id,
            subject=None,
            is_admin=True,
            after_event_id=last_event_id,
        )
        if queue is None:
            return

        try:
            # Replay buffered events
            for event in replay_events:
                yield _format_sse_frame(event)

            # Live event loop
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield _format_sse_frame(event)
                except TimeoutError:
                    continue
        finally:
            await self._ws_manager.unsubscribe_sse(run_id, queue)

    # -- statistics ---------------------------------------------------------

    async def get_transport_stats(self) -> dict[str, Any]:
        """Return current transport statistics."""
        ws_bridge_total = await self._bridge.total_subscribers()
        ws_bridge_runs = await self._bridge.active_runs()

        ws_manager_connections = 0
        sse_manager_connections = 0
        if self._ws_manager is not None:
            ws_manager_connections = await self._ws_manager.connected_count()

        async with self._stats_lock:
            total_ws = self._total_ws_served
            total_sse = self._total_sse_served

        return {
            "transport_preferred": self._config.preferred.value,
            "active_ws_connections": ws_bridge_total + ws_manager_connections,
            "active_ws_bridge_subscribers": ws_bridge_total,
            "active_ws_bridge_runs": ws_bridge_runs,
            "active_ws_manager_connections": ws_manager_connections,
            "active_sse_streams": sse_manager_connections,
            "total_ws_served": total_ws,
            "total_sse_served": total_sse,
            "total_served": total_ws + total_sse,
            "config": {
                "preferred": self._config.preferred.value,
                "ws_ping_interval": self._config.ws_ping_interval,
                "ws_ping_timeout": self._config.ws_ping_timeout,
                "sse_retry_ms": self._config.sse_retry_ms,
                "max_reconnect_attempts": self._config.max_reconnect_attempts,
            },
            "uptime_seconds": round(time.time() - self._created_at, 2),
        }


# ---------------------------------------------------------------------------
# SSE formatting helper
# ---------------------------------------------------------------------------


def _format_sse_frame(event: WorkflowEvent) -> str:
    """Serialize a :class:`WorkflowEvent` as an SSE ``data:`` frame."""
    lines: list[str] = []
    if event.event_id:
        lines.append(f"id: {event.event_id}")
    payload = event.to_json()
    for line in payload.splitlines() or [payload]:
        lines.append(f"data: {line}")
    return "\n".join(lines) + "\n\n"
