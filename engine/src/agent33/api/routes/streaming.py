"""WebSocket streaming endpoint for real-time agent invocation events.

P2.5 -- Provides a WebSocket transport layer that streams structured
progress events (thinking, tool_call, response, error, done) back to
connected clients during agent invocations.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from fastapi import APIRouter
from jwt import InvalidTokenError
from pydantic import BaseModel, Field
from starlette.websockets import WebSocket, WebSocketDisconnect

from agent33.config import settings
from agent33.security.auth import validate_api_key, verify_token
from agent33.security.permissions import check_permission

if TYPE_CHECKING:
    from agent33.security.auth import TokenPayload

logger = structlog.get_logger()

router = APIRouter(tags=["streaming"])


# ---------------------------------------------------------------------------
# Event model
# ---------------------------------------------------------------------------


class StreamEvent(BaseModel):
    """A single streaming event sent over the WebSocket connection."""

    event: str = Field(description="Event type: thinking, tool_call, response, error, done")
    data: dict[str, Any] = Field(default_factory=dict)
    seq: int = Field(description="Monotonically increasing sequence number")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO 8601 timestamp",
    )

    def to_json(self) -> str:
        return self.model_dump_json()


# ---------------------------------------------------------------------------
# Streaming manager
# ---------------------------------------------------------------------------


class StreamingManager:
    """Manages active WebSocket streaming connections.

    Each connection is keyed by a ``session_id`` that the caller provides
    at connect time.  The manager enforces a configurable maximum connection
    limit and provides a ``broadcast`` helper that sends an event to all
    connections sharing a session.
    """

    def __init__(self, max_connections: int = 100) -> None:
        self._connections: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()
        self._max_connections = max(1, max_connections)

    @property
    def active_count(self) -> int:
        """Total number of tracked WebSocket connections across all sessions."""
        return sum(len(ws_set) for ws_set in self._connections.values())

    async def connect(
        self,
        websocket: WebSocket,
        session_id: str,
    ) -> bool:
        """Register *websocket* under *session_id*.

        Returns ``False`` if the maximum connection limit has been reached.
        """
        async with self._lock:
            if self.active_count >= self._max_connections:
                return False
            self._connections.setdefault(session_id, set()).add(websocket)
        logger.debug(
            "streaming_ws_connected",
            session_id=session_id,
            active=self.active_count,
        )
        return True

    async def disconnect(self, websocket: WebSocket, session_id: str) -> None:
        """Remove *websocket* from the tracked set for *session_id*."""
        async with self._lock:
            ws_set = self._connections.get(session_id)
            if ws_set is not None:
                ws_set.discard(websocket)
                if not ws_set:
                    del self._connections[session_id]
        logger.debug(
            "streaming_ws_disconnected",
            session_id=session_id,
            active=self.active_count,
        )

    async def broadcast(self, session_id: str, event: StreamEvent) -> None:
        """Send *event* to every connection associated with *session_id*."""
        async with self._lock:
            targets = list(self._connections.get(session_id, set()))

        payload = event.to_json()
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                ws_set = self._connections.get(session_id)
                if ws_set is not None:
                    for ws in dead:
                        ws_set.discard(ws)
                    if not ws_set:
                        del self._connections[session_id]

    async def session_connections(self, session_id: str) -> int:
        """Return the number of active connections for *session_id*."""
        async with self._lock:
            return len(self._connections.get(session_id, set()))


# ---------------------------------------------------------------------------
# WebSocket authentication (mirrors workflow_ws.py pattern)
# ---------------------------------------------------------------------------


def _extract_streaming_credentials(
    websocket: WebSocket,
) -> tuple[str | None, str | None, str]:
    """Extract exactly one credential from headers or query params.

    Returns ``(token, api_key, source)`` where *source* indicates where
    the credential was found (``"header"``, ``"query"``, ``"ambiguous"``,
    or ``"missing"``).
    """
    authorization = websocket.headers.get("authorization", "")
    header_token = authorization[7:] if authorization.startswith("Bearer ") else None
    header_api_key = websocket.headers.get("x-api-key")
    query_token = websocket.query_params.get("token")
    query_api_key = websocket.query_params.get("api_key")

    provided = [
        credential
        for credential in (header_token, header_api_key, query_token, query_api_key)
        if credential
    ]
    if len(provided) > 1:
        return None, None, "ambiguous"

    if header_token:
        return header_token, None, "header"
    if header_api_key:
        return None, header_api_key, "header"
    if query_token:
        logger.debug("streaming_ws_query_auth_used", transport="token")
        return query_token, None, "query"
    if query_api_key:
        logger.debug("streaming_ws_query_auth_used", transport="api_key")
        return None, query_api_key, "query"
    return None, None, "missing"


async def _authenticate_streaming_ws(websocket: WebSocket) -> TokenPayload | None:
    """Authenticate a streaming WebSocket connection.

    On failure the socket is closed with code 4001 and ``None`` is returned.
    On missing scope the socket is closed with code 4003.
    """
    token, api_key, source = _extract_streaming_credentials(websocket)

    payload = None
    if token:
        try:
            payload = verify_token(token)
        except InvalidTokenError:
            logger.debug("streaming_ws_token_invalid", source=source)
            payload = None
    elif api_key:
        payload = validate_api_key(api_key)

    if payload is None:
        await websocket.close(code=4001, reason="Invalid or missing credentials")
        return None

    if not check_permission("agents:invoke", payload.scopes):
        await websocket.close(code=4003, reason="Missing required scope: agents:invoke")
        return None

    return payload


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


@router.websocket("/v1/stream/agent/{agent_id}")
async def stream_agent(websocket: WebSocket, agent_id: str) -> None:
    """Stream real-time progress events for an agent invocation.

    Protocol:

    1. Client connects and is authenticated via JWT/API-key.
    2. Client sends a single JSON message: ``{"input": str, "context": dict}``.
    3. Server streams ``StreamEvent`` JSON messages back.
    4. Server sends a ``done`` event and closes the connection.
    """
    payload = await _authenticate_streaming_ws(websocket)
    if payload is None:
        return

    manager: StreamingManager | None = getattr(websocket.app.state, "streaming_manager", None)
    if manager is None:
        await websocket.close(code=4002, reason="Streaming manager not available")
        return

    await websocket.accept()

    # Use a unique session id for this connection.
    session_id = f"{agent_id}:{payload.sub}:{id(websocket)}"

    connected = await manager.connect(websocket, session_id)
    if not connected:
        error_event = StreamEvent(
            event="error",
            data={"error": "Maximum connections reached"},
            seq=0,
        )
        await websocket.send_text(error_event.to_json())
        await websocket.close(code=4029, reason="Too many connections")
        return

    ping_task: asyncio.Task[None] | None = None
    try:
        # Wait for the initial input message from the client.
        raw = await websocket.receive_text()
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            error_event = StreamEvent(
                event="error",
                data={"error": "Invalid JSON in initial message"},
                seq=0,
            )
            await websocket.send_text(error_event.to_json())
            return

        # Validate the input message shape.
        user_input = msg.get("input")
        context = msg.get("context", {})
        if not isinstance(user_input, str) or not user_input.strip():
            error_event = StreamEvent(
                event="error",
                data={"error": "Missing or empty 'input' field"},
                seq=0,
            )
            await websocket.send_text(error_event.to_json())
            return

        if not isinstance(context, dict):
            error_event = StreamEvent(
                event="error",
                data={"error": "'context' must be a JSON object"},
                seq=0,
            )
            await websocket.send_text(error_event.to_json())
            return

        # Start keepalive ping task.
        ping_interval = settings.streaming_ping_interval_seconds
        ping_task = asyncio.create_task(
            _ping_loop(websocket, ping_interval),
        )

        # Stream events for this invocation.
        seq = 0

        # Emit initial thinking event.
        seq += 1
        await websocket.send_text(
            StreamEvent(
                event="thinking",
                data={"agent_id": agent_id, "status": "processing"},
                seq=seq,
            ).to_json()
        )

        # Resolve the agent from the registry.
        registry = getattr(websocket.app.state, "agent_registry", None)
        agent_def = None
        if registry is not None:
            agent_def = registry.get(agent_id) or registry.get_by_agent_id(agent_id)

        if agent_def is None:
            seq += 1
            await websocket.send_text(
                StreamEvent(
                    event="error",
                    data={"error": f"Agent '{agent_id}' not found"},
                    seq=seq,
                ).to_json()
            )
            seq += 1
            await websocket.send_text(StreamEvent(event="done", data={}, seq=seq).to_json())
            return

        # Attempt real agent invocation via the model router.
        model_router = getattr(websocket.app.state, "model_router", None)
        if model_router is not None:
            try:
                from agent33.agents.runtime import AgentRuntime

                runtime = AgentRuntime(
                    definition=agent_def,
                    router=model_router,
                    session_id=session_id,
                    invocation_mode="streaming",
                    tenant_id=payload.tenant_id,
                )
                result = await runtime.invoke({"query": user_input, **context})

                seq += 1
                await websocket.send_text(
                    StreamEvent(
                        event="response",
                        data={
                            "agent": agent_def.name,
                            "output": result.output,
                            "tokens_used": result.tokens_used,
                            "model": result.model,
                        },
                        seq=seq,
                    ).to_json()
                )
            except Exception as exc:
                seq += 1
                await websocket.send_text(
                    StreamEvent(
                        event="error",
                        data={"error": str(exc)},
                        seq=seq,
                    ).to_json()
                )
        else:
            # No model router available -- return agent metadata as a
            # diagnostic response so the transport is exercised end-to-end.
            seq += 1
            await websocket.send_text(
                StreamEvent(
                    event="response",
                    data={
                        "agent": agent_def.name,
                        "message": "Agent found; model router unavailable",
                        "input_received": user_input,
                    },
                    seq=seq,
                ).to_json()
            )

        # Send done event.
        seq += 1
        await websocket.send_text(
            StreamEvent(event="done", data={"total_events": seq}, seq=seq).to_json()
        )

    except asyncio.CancelledError:
        raise
    except WebSocketDisconnect:
        logger.debug("streaming_ws_client_disconnected", agent_id=agent_id)
    except Exception:
        logger.debug("streaming_ws_error", agent_id=agent_id, exc_info=True)
    finally:
        if ping_task is not None:
            ping_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ping_task
        await manager.disconnect(websocket, session_id)


async def _ping_loop(websocket: WebSocket, interval: int) -> None:
    """Send periodic ping events to keep the connection alive."""
    seq = 0
    try:
        while True:
            await asyncio.sleep(interval)
            seq += 1
            ping_event = StreamEvent(
                event="thinking",
                data={"ping": True, "ts": time.time()},
                seq=seq,
            )
            await websocket.send_text(ping_event.to_json())
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.debug("streaming_ws_ping_stopped", exc_info=True)
