"""SSE endpoint for real-time run-scoped workflow status streaming."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from agent33.security.permissions import require_scope
from agent33.workflows.events import WorkflowEvent, WorkflowEventType

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

router = APIRouter(prefix="/v1/workflows", tags=["workflows"])


@router.get("/{run_id}/events", dependencies=[require_scope("workflows:read")])
async def stream_workflow_events(run_id: str, request: Request) -> StreamingResponse:
    """Stream run-scoped workflow events over authenticated SSE."""
    user = _get_request_user(request)
    manager = getattr(request.app.state, "ws_manager", None)
    if manager is None:
        return _archived_workflow_events_response(run_id, request, user)

    queue, replay_events = await manager.subscribe_sse_with_replay_if_allowed(
        run_id,
        subject=user.sub,
        tenant_id=getattr(user, "tenant_id", ""),
        scopes=getattr(user, "scopes", []),
        is_admin="admin" in getattr(user, "scopes", []),
        after_event_id=request.headers.get("last-event-id"),
    )
    if queue is None:
        return _archived_workflow_events_response(run_id, request, user)

    sync_event = await manager.build_sync_event(run_id)
    if sync_event is None:
        await manager.unsubscribe_sse(run_id, queue)
        return _archived_workflow_events_response(run_id, request, user)

    async def event_generator() -> AsyncGenerator[str, None]:
        loop = asyncio.get_running_loop()
        poll_timeout = min(manager.heartbeat_interval_seconds, 1.0)
        next_heartbeat_at = loop.time() + manager.heartbeat_interval_seconds
        try:
            yield _format_sse(sync_event)
            for replay_event in replay_events:
                yield _format_sse(replay_event)
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(
                        queue.get(),
                        timeout=poll_timeout,
                    )
                    next_heartbeat_at = loop.time() + manager.heartbeat_interval_seconds
                except TimeoutError:
                    if loop.time() < next_heartbeat_at:
                        continue
                    heartbeat = await manager.build_heartbeat_event(run_id)
                    if heartbeat is None:
                        break
                    yield _format_sse(heartbeat)
                    next_heartbeat_at = loop.time() + manager.heartbeat_interval_seconds
                    continue
                yield _format_sse(event)
        finally:
            await manager.unsubscribe_sse(run_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _archived_workflow_events_response(
    run_id: str,
    request: Request,
    user: Any,
) -> StreamingResponse:
    archived = _get_archived_run_detail(run_id, request, user)
    sync_event = _build_archived_sync_event(run_id, archived)
    replay_events = _archived_replay_events(
        archived,
        after_event_id=request.headers.get("last-event-id"),
    )

    async def event_generator() -> AsyncGenerator[str, None]:
        yield _format_sse(sync_event)
        for replay_event in replay_events:
            yield _format_sse(replay_event)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _get_archived_run_detail(run_id: str, request: Request, user: Any) -> dict[str, Any]:
    from agent33.api.routes import workflows as workflow_routes

    archived = workflow_routes.get_workflow_run_archive_service()
    if archived is None:
        raise HTTPException(status_code=404, detail=f"Workflow run '{run_id}' not found")
    try:
        detail = archived.get_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=f"Workflow run '{run_id}' not found") from exc
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Workflow run '{run_id}' not found")
    run_payload = detail.get("run", {})
    if not isinstance(run_payload, dict):
        raise HTTPException(status_code=404, detail=f"Workflow run '{run_id}' not found")
    if not workflow_routes.tenant_access_allowed(
        str(run_payload.get("tenant_id", "")),
        requester_tenant_id=getattr(user, "tenant_id", ""),
        requester_scopes=list(getattr(user, "scopes", [])),
    ):
        raise HTTPException(status_code=404, detail=f"Workflow run '{run_id}' not found")
    return detail


def _build_archived_sync_event(run_id: str, archived: dict[str, Any]) -> WorkflowEvent:
    run_payload = archived.get("run", {})
    history_payload = archived.get("history", {})
    workflow_name = str(run_payload.get("workflow_name", "")).strip()
    updated_at = float(run_payload.get("updated_at") or run_payload.get("completed_at") or 0.0)
    return WorkflowEvent(
        event_type=WorkflowEventType.SYNC,
        run_id=run_id,
        workflow_name=workflow_name,
        timestamp=updated_at or float(run_payload.get("started_at") or 0.0),
        data={
            "status": str(run_payload.get("status", "completed")),
            "step_statuses": history_payload.get("step_statuses", {})
            if isinstance(history_payload, dict)
            else {},
            "last_event_type": _last_archived_event_type(archived),
            "terminal": True,
            "updated_at": updated_at,
            "error": run_payload.get("error"),
            "duration_ms": run_payload.get("duration_ms"),
        },
    )


def _archived_replay_events(
    archived: dict[str, Any],
    *,
    after_event_id: str | None,
) -> list[WorkflowEvent]:
    raw_events = archived.get("events", [])
    if not isinstance(raw_events, list):
        return []
    cursor = _parse_event_cursor(after_event_id)
    replay_events: list[WorkflowEvent] = []
    for payload in raw_events:
        if not isinstance(payload, dict):
            continue
        event_cursor = _parse_event_cursor(payload.get("event_id"))
        if cursor is not None and (event_cursor is None or event_cursor <= cursor):
            continue
        replay_events.append(
            WorkflowEvent(
                event_type=WorkflowEventType(
                    str(payload.get("type", WorkflowEventType.SYNC.value)),
                ),
                run_id=str(payload.get("run_id", "")),
                workflow_name=str(payload.get("workflow_name", "")),
                timestamp=float(payload.get("timestamp", 0.0)),
                step_id=(
                    str(payload.get("step_id")) if payload.get("step_id") is not None else None
                ),
                data=(
                    payload.get("data", {}) if isinstance(payload.get("data", {}), dict) else {}
                ),
                event_id=(
                    str(payload.get("event_id")) if payload.get("event_id") is not None else None
                ),
                schema_version=int(payload.get("schema_version", 1)),
            )
        )
    return replay_events


def _last_archived_event_type(archived: dict[str, Any]) -> str | None:
    raw_events = archived.get("events", [])
    if not isinstance(raw_events, list) or not raw_events:
        return None
    last = raw_events[-1]
    if not isinstance(last, dict):
        return None
    value = last.get("type")
    return str(value) if value is not None else None


def _format_sse(event: WorkflowEvent) -> str:
    """Serialize a workflow event as a single SSE data frame."""
    frame_lines: list[str] = []
    if event.event_id:
        frame_lines.append(f"id: {event.event_id}")
    payload = event.to_json()
    for line in payload.splitlines() or [payload]:
        frame_lines.append(f"data: {line}")
    return "\n".join(frame_lines) + "\n\n"


def _get_request_user(request: Request) -> Any:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def _parse_event_cursor(value: Any) -> int | None:
    if value is None:
        return None
    candidate = str(value).strip()
    if not candidate:
        return None
    try:
        parsed = int(candidate)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None
