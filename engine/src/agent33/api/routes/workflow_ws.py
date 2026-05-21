"""WebSocket endpoint for real-time run-scoped workflow status streaming."""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import TYPE_CHECKING, Any

import structlog
from fastapi import APIRouter
from jwt import InvalidTokenError
from starlette.websockets import WebSocket, WebSocketDisconnect

from agent33.security.auth import validate_api_key, verify_token
from agent33.security.permissions import check_permission

if TYPE_CHECKING:
    from agent33.security.auth import TokenPayload
    from agent33.workflows.ws_manager import WorkflowWSManager

logger = structlog.get_logger()

router = APIRouter(tags=["workflows"])


@router.websocket("/v1/workflows/{run_id}/ws")
async def workflow_ws(websocket: WebSocket, run_id: str) -> None:
    """Stream run-scoped events for the execution identified by ``run_id``."""
    payload = await _authenticate_websocket(websocket)
    if payload is None:
        return

    manager: WorkflowWSManager | None = getattr(websocket.app.state, "ws_manager", None)
    if manager is None:
        await websocket.close(code=4002, reason="WebSocket manager not available")
        return

    if not await manager.can_access_run(
        run_id,
        subject=payload.sub,
        tenant_id=payload.tenant_id,
        scopes=payload.scopes,
    ):
        await websocket.close(code=4004, reason="Unknown run_id")
        return

    await websocket.accept()

    connected = await manager.connect(websocket, run_id)
    if not connected:
        await websocket.close(code=4004, reason="Unknown run_id")
        return

    try:
        if not await manager.send_sync(websocket, run_id):
            await websocket.close(code=4004, reason="Unknown run_id")
            return
    except asyncio.CancelledError:
        raise
    except Exception:
        await manager.disconnect(websocket)
        return

    heartbeat_task = asyncio.create_task(_heartbeat_loop(websocket, manager, run_id))
    logger.debug("ws_workflow_connected", run_id=run_id, subject=payload.sub)

    try:
        while True:
            raw = await websocket.receive_text()
            await _handle_client_message(websocket, manager, run_id, raw)
    except asyncio.CancelledError:
        raise
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.debug("ws_workflow_error", run_id=run_id, exc_info=True)
    finally:
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task
        await manager.disconnect(websocket)
        logger.debug("ws_workflow_disconnected", run_id=run_id)


async def _authenticate_websocket(websocket: WebSocket) -> TokenPayload | None:
    """Authenticate the WebSocket request.

    Header-based credentials are preferred. Query-string transport remains available
    for browser WebSocket clients that cannot set custom headers during the handshake.
    """
    token, api_key, source = _extract_websocket_credentials(websocket)

    payload = None
    if token:
        try:
            payload = verify_token(token)
        except InvalidTokenError:
            logger.debug("ws_token_invalid", source=source)
            payload = None
    elif api_key:
        payload = validate_api_key(api_key)

    if payload is None:
        await websocket.close(code=4001, reason="Invalid or missing credentials")
        return None

    if not check_permission("workflows:read", payload.scopes):
        await websocket.close(code=4003, reason="Missing required scope")
        return None

    return payload


def _extract_websocket_credentials(websocket: WebSocket) -> tuple[str | None, str | None, str]:
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
        logger.debug("ws_query_auth_used", transport="token")
        return query_token, None, "query"
    if query_api_key:
        logger.debug("ws_query_auth_used", transport="api_key")
        return None, query_api_key, "query"
    return None, None, "missing"


async def _handle_client_message(
    websocket: WebSocket,
    manager: WorkflowWSManager,
    run_id: str,
    raw: str,
) -> None:
    """Parse and dispatch a single client JSON message."""
    try:
        msg: dict[str, Any] = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        await websocket.send_json({"type": "error", "message": "Invalid JSON"})
        return

    action = msg.get("action")

    if action == "ping":
        await websocket.send_json({"type": "pong", "run_id": run_id})
        return

    if action == "sync":
        await manager.send_sync(websocket, run_id)
        return

    await websocket.send_json({"type": "error", "message": f"Unknown action: {action}"})


async def _heartbeat_loop(
    websocket: WebSocket,
    manager: WorkflowWSManager,
    run_id: str,
) -> None:
    """Send periodic keepalive events while the socket remains connected."""
    try:
        while True:
            await asyncio.sleep(manager.heartbeat_interval_seconds)
            await manager.send_heartbeat(websocket, run_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.debug("ws_workflow_heartbeat_stopped", run_id=run_id, exc_info=True)
