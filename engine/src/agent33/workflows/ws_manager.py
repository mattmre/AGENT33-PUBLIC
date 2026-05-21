"""WebSocket connection manager for run-scoped workflow event streaming."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

import structlog

from agent33.security.permissions import check_permission
from agent33.workflows.events import (
    WorkflowEvent,
    WorkflowEventType,
    resolve_active_schema_version,
)

if TYPE_CHECKING:
    from starlette.websockets import WebSocket

logger = structlog.get_logger()


@dataclass
class WorkflowRunSnapshot:
    """Current server-side view of a workflow execution run."""

    run_id: str
    workflow_name: str
    owner_subject: str | None = None
    tenant_id: str | None = None
    status: str = "pending"
    step_statuses: dict[str, str] = field(default_factory=dict)
    last_event_type: str | None = None
    updated_at: float = field(default_factory=time.time)
    terminal: bool = False
    error: str | None = None
    duration_ms: float | None = None
    last_event_id: int = 0
    schema_version: int = field(default_factory=resolve_active_schema_version)

    def to_event_data(self) -> dict[str, Any]:
        """Return the transport payload used by sync events."""
        data: dict[str, Any] = {
            "status": self.status,
            "step_statuses": dict(self.step_statuses),
            "last_event_type": self.last_event_type,
            "terminal": self.terminal,
            "updated_at": self.updated_at,
        }
        if self.error is not None:
            data["error"] = self.error
        if self.duration_ms is not None:
            data["duration_ms"] = self.duration_ms
        return data


@dataclass
class _PendingMessage:
    payload: str
    delivered: asyncio.Future[bool] | None = None


@dataclass
class _ConnectionState:
    queue: asyncio.Queue[_PendingMessage] = field(default_factory=asyncio.Queue)
    sender_task: asyncio.Task[None] | None = None


class WorkflowWSManager:
    """Manages WebSocket subscriptions and snapshots for workflow runs."""

    def __init__(
        self,
        heartbeat_interval_seconds: float = 30.0,
        sse_queue_maxsize: int = 100,
        sse_replay_buffer_size: int = 200,
        archive_service: Any | None = None,
    ) -> None:
        self._subscriptions: dict[str, set[Any]] = {}
        self._reverse: dict[Any, set[str]] = {}
        self._connections: dict[Any, _ConnectionState] = {}
        self._sse_subscriptions: dict[str, set[asyncio.Queue[WorkflowEvent]]] = {}
        self._sse_replay_buffers: dict[str, deque[WorkflowEvent]] = {}
        self._snapshots: dict[str, WorkflowRunSnapshot] = {}
        self._lock = asyncio.Lock()
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.sse_queue_maxsize = max(1, sse_queue_maxsize)
        self.sse_replay_buffer_size = max(1, sse_replay_buffer_size)
        self._archive_service = archive_service

    def set_archive_service(self, archive_service: Any | None) -> None:
        """Attach an optional durable archive service for workflow events."""
        self._archive_service = archive_service

    async def register_run(
        self,
        run_id: str,
        workflow_name: str,
        *,
        owner_subject: str | None = None,
        tenant_id: str = "",
        schema_version: int | None = None,
    ) -> None:
        """Ensure a snapshot exists for *run_id*."""
        async with self._lock:
            snapshot = self._snapshots.setdefault(
                run_id,
                WorkflowRunSnapshot(
                    run_id=run_id,
                    workflow_name=workflow_name,
                    owner_subject=owner_subject,
                    tenant_id=tenant_id or None,
                    schema_version=schema_version or resolve_active_schema_version(),
                ),
            )
            snapshot.workflow_name = workflow_name
            if owner_subject is not None:
                snapshot.owner_subject = owner_subject
            if tenant_id:
                snapshot.tenant_id = tenant_id
            self._sse_replay_buffers.setdefault(
                run_id,
                deque(maxlen=self.sse_replay_buffer_size),
            )

    async def has_run(self, run_id: str) -> bool:
        """Return ``True`` when *run_id* is known to the manager."""
        async with self._lock:
            return run_id in self._snapshots

    async def can_access_run(
        self,
        run_id: str,
        *,
        subject: str | None = None,
        tenant_id: str = "",
        scopes: list[str] | None = None,
        is_admin: bool = False,
    ) -> bool:
        """Return ``True`` when the caller can access *run_id*."""
        async with self._lock:
            snapshot = self._snapshots.get(run_id)

        if snapshot is None:
            return False

        if is_admin or check_permission("admin", scopes or []):
            return True
        if snapshot.tenant_id and snapshot.tenant_id != tenant_id:
            return False
        return not snapshot.owner_subject or snapshot.owner_subject == subject

    async def connect(self, ws: WebSocket, run_id: str) -> bool:
        """Subscribe *ws* to a single workflow *run_id*."""
        async with self._lock:
            if run_id not in self._snapshots:
                return False

            state = self._connections.get(ws)
            if state is None:
                state = _ConnectionState()
                state.sender_task = asyncio.create_task(self._sender_loop(ws, state))
                self._connections[ws] = state

            self._subscriptions.setdefault(run_id, set()).add(ws)
            self._reverse.setdefault(ws, set()).add(run_id)

        logger.debug(
            "ws_run_connected",
            run_id=run_id,
            active_subs=await self.active_subscriptions(run_id),
        )
        return True

    async def disconnect(self, ws: WebSocket) -> None:
        """Remove *ws* from all tracked subscriptions."""
        sender_task: asyncio.Task[None] | None = None
        async with self._lock:
            run_ids = list(self._reverse.pop(ws, set()))
            for run_id in run_ids:
                subs = self._subscriptions.get(run_id)
                if subs is not None:
                    subs.discard(ws)
                    if not subs:
                        del self._subscriptions[run_id]
            state = self._connections.pop(ws, None)
            if state is not None:
                sender_task = state.sender_task

        if sender_task is not None and sender_task is not asyncio.current_task():
            sender_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sender_task

        if run_ids:
            logger.debug("ws_disconnected", removed_subscriptions=len(run_ids))

    async def subscribe_sse(self, run_id: str) -> asyncio.Queue[WorkflowEvent] | None:
        """Register and return an SSE queue for *run_id*."""
        queue: asyncio.Queue[WorkflowEvent] = asyncio.Queue(maxsize=self.sse_queue_maxsize)
        async with self._lock:
            if run_id not in self._snapshots:
                return None
            self._sse_subscriptions.setdefault(run_id, set()).add(queue)
        return queue

    async def subscribe_sse_if_allowed(
        self,
        run_id: str,
        *,
        subject: str | None,
        tenant_id: str = "",
        scopes: list[str] | None = None,
        is_admin: bool = False,
    ) -> asyncio.Queue[WorkflowEvent] | None:
        """Atomically authorize and subscribe an SSE client for *run_id*."""
        queue: asyncio.Queue[WorkflowEvent] = asyncio.Queue(maxsize=self.sse_queue_maxsize)
        async with self._lock:
            snapshot = self._snapshots.get(run_id)
            if snapshot is None:
                return None
            if not (is_admin or check_permission("admin", scopes or [])):
                if snapshot.tenant_id and snapshot.tenant_id != tenant_id:
                    return None
                if snapshot.owner_subject and snapshot.owner_subject != subject:
                    return None
            self._sse_subscriptions.setdefault(run_id, set()).add(queue)
        return queue

    async def subscribe_sse_with_replay_if_allowed(
        self,
        run_id: str,
        *,
        subject: str | None,
        tenant_id: str = "",
        scopes: list[str] | None = None,
        is_admin: bool = False,
        after_event_id: str | None = None,
    ) -> tuple[asyncio.Queue[WorkflowEvent] | None, list[WorkflowEvent]]:
        """Atomically authorize, subscribe, and capture replay events."""
        queue: asyncio.Queue[WorkflowEvent] = asyncio.Queue(maxsize=self.sse_queue_maxsize)
        async with self._lock:
            snapshot = self._snapshots.get(run_id)
            if snapshot is None:
                return None, []
            if not (is_admin or check_permission("admin", scopes or [])):
                if snapshot.tenant_id and snapshot.tenant_id != tenant_id:
                    return None, []
                if snapshot.owner_subject and snapshot.owner_subject != subject:
                    return None, []
            replay_events = self._replay_events_unlocked(run_id, after_event_id)
            self._sse_subscriptions.setdefault(run_id, set()).add(queue)
        return queue, replay_events

    async def unsubscribe_sse(
        self,
        run_id: str,
        queue: asyncio.Queue[WorkflowEvent],
    ) -> None:
        """Remove a previously registered SSE queue for *run_id*."""
        async with self._lock:
            subscribers = self._sse_subscriptions.get(run_id)
            if subscribers is None:
                return
            subscribers.discard(queue)
            if not subscribers:
                del self._sse_subscriptions[run_id]

    async def publish_event(self, event: WorkflowEvent) -> WorkflowEvent:
        """Update the run snapshot and fan out *event* to subscribers."""
        async with self._lock:
            snapshot = self._snapshots.setdefault(
                event.run_id,
                WorkflowRunSnapshot(
                    run_id=event.run_id,
                    workflow_name=event.workflow_name,
                    schema_version=event.schema_version,
                ),
            )
            event = self._coerce_event_schema_version(snapshot, event)
            event = self._assign_event_id(snapshot, event)
            self._apply_event(snapshot, event)
            self._sse_replay_buffers.setdefault(
                event.run_id,
                deque(maxlen=self.sse_replay_buffer_size),
            ).append(event)
            targets = list(self._subscriptions.get(event.run_id, set()))
            sse_targets = list(self._sse_subscriptions.get(event.run_id, set()))
            archive_service = self._archive_service

        if archive_service is not None:
            try:
                archive_service.append_event(event.run_id, event)
            except Exception:
                logger.warning(
                    "workflow_archive_append_failed",
                    run_id=event.run_id,
                    event_type=event.event_type.value,
                    exc_info=True,
                )

        for queue in sse_targets:
            if not self._publish_sse_event(queue, event, run_id=event.run_id):
                logger.warning("sse_event_dropped", run_id=event.run_id)

        if not targets:
            return event

        payload = event.to_json()
        dead: list[Any] = []
        for ws in targets:
            delivered = await self._enqueue_text(ws, payload)
            if not delivered:
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    self._remove_ws_unlocked(ws)
            logger.debug("ws_dead_connections_cleaned", count=len(dead))
        return event

    async def build_sync_event(self, run_id: str) -> WorkflowEvent | None:
        """Build a transport-neutral snapshot event for *run_id*."""
        async with self._lock:
            snapshot = self._snapshots.get(run_id)
            if snapshot is None:
                return None
            data = snapshot.to_event_data()
            workflow_name = snapshot.workflow_name
            schema_version = snapshot.schema_version

        return WorkflowEvent(
            event_type=WorkflowEventType.SYNC,
            run_id=run_id,
            workflow_name=workflow_name,
            data=data,
            schema_version=schema_version,
        )

    async def send_sync(self, ws: WebSocket, run_id: str) -> bool:
        """Send the latest snapshot for *run_id* to *ws*."""
        event = await self.build_sync_event(run_id)
        if event is None:
            return False
        return await self._enqueue_text(ws, event.to_json(), wait=True)

    async def build_heartbeat_event(self, run_id: str) -> WorkflowEvent | None:
        """Build a transport-neutral heartbeat event for *run_id*."""
        async with self._lock:
            snapshot = self._snapshots.get(run_id)
            if snapshot is None:
                return None
            workflow_name = snapshot.workflow_name
            status = snapshot.status
            terminal = snapshot.terminal
            schema_version = snapshot.schema_version

        return WorkflowEvent(
            event_type=WorkflowEventType.HEARTBEAT,
            run_id=run_id,
            workflow_name=workflow_name,
            data={"status": status, "terminal": terminal},
            schema_version=schema_version,
        )

    async def replay_sse_events(
        self,
        run_id: str,
        after_event_id: str | None,
    ) -> list[WorkflowEvent]:
        """Return buffered SSE events after the provided cursor."""
        async with self._lock:
            return self._replay_events_unlocked(run_id, after_event_id)

    async def send_heartbeat(self, ws: WebSocket, run_id: str) -> bool:
        """Send a heartbeat event for *run_id* to *ws*."""
        event = await self.build_heartbeat_event(run_id)
        if event is None:
            return False
        return await self._enqueue_text(ws, event.to_json(), wait=True)

    async def active_subscriptions(self, run_id: str) -> int:
        """Return the number of active subscribers for *run_id*."""
        async with self._lock:
            return len(self._subscriptions.get(run_id, set()))

    async def active_sse_subscriptions(self, run_id: str) -> int:
        """Return the number of active SSE subscribers for *run_id*."""
        async with self._lock:
            return len(self._sse_subscriptions.get(run_id, set()))

    async def connected_count(self) -> int:
        """Return the total number of tracked WebSocket connections."""
        async with self._lock:
            return len(self._reverse)

    def _apply_event(self, snapshot: WorkflowRunSnapshot, event: WorkflowEvent) -> None:
        snapshot.workflow_name = event.workflow_name
        snapshot.last_event_type = event.event_type.value
        snapshot.updated_at = event.timestamp

        if event.event_type == WorkflowEventType.WORKFLOW_STARTED:
            snapshot.status = "running"
            snapshot.terminal = False
            snapshot.error = None
            return

        if event.event_type == WorkflowEventType.STEP_STARTED and event.step_id:
            snapshot.status = "running"
            snapshot.step_statuses[event.step_id] = "running"
            return

        if event.event_type == WorkflowEventType.STEP_COMPLETED and event.step_id:
            snapshot.step_statuses[event.step_id] = "success"
            return

        if event.event_type == WorkflowEventType.STEP_SKIPPED and event.step_id:
            snapshot.step_statuses[event.step_id] = "skipped"
            return

        if event.event_type == WorkflowEventType.STEP_RETRYING and event.step_id:
            snapshot.step_statuses[event.step_id] = "retrying"
            snapshot.error = event.data.get("error")
            return

        if event.event_type == WorkflowEventType.STEP_FAILED and event.step_id:
            snapshot.step_statuses[event.step_id] = "failed"
            snapshot.error = event.data.get("error")
            return

        if event.event_type == WorkflowEventType.WORKFLOW_COMPLETED:
            snapshot.status = str(event.data.get("status", "success"))
            snapshot.duration_ms = _coerce_float(event.data.get("duration_ms"))
            snapshot.error = None
            snapshot.terminal = True
            return

        if event.event_type == WorkflowEventType.WORKFLOW_FAILED:
            snapshot.status = str(event.data.get("status", "failed"))
            snapshot.duration_ms = _coerce_float(event.data.get("duration_ms"))
            snapshot.error = event.data.get("error")
            snapshot.terminal = True

    def _coerce_event_schema_version(
        self,
        snapshot: WorkflowRunSnapshot,
        event: WorkflowEvent,
    ) -> WorkflowEvent:
        if event.schema_version == snapshot.schema_version:
            return event
        return replace(event, schema_version=snapshot.schema_version)

    def _remove_ws_unlocked(self, ws: Any) -> None:
        run_ids = list(self._reverse.pop(ws, set()))
        for run_id in run_ids:
            subs = self._subscriptions.get(run_id)
            if subs is not None:
                subs.discard(ws)
                if not subs:
                    del self._subscriptions[run_id]
        self._connections.pop(ws, None)

    async def _enqueue_text(self, ws: Any, payload: str, *, wait: bool = False) -> bool:
        async with self._lock:
            state = self._connections.get(ws)
            if state is None or state.sender_task is None or state.sender_task.done():
                state = None
            delivered: asyncio.Future[bool] | None = None
            if state is not None and wait:
                delivered = asyncio.get_running_loop().create_future()
            if state is not None:
                state.queue.put_nowait(_PendingMessage(payload=payload, delivered=delivered))

        if state is None:
            if not wait:
                return False
            try:
                await ws.send_text(payload)
            except asyncio.CancelledError:
                raise
            except Exception:
                return False
            return True

        if delivered is None:
            return True

        try:
            return await delivered
        except asyncio.CancelledError:
            raise

    async def _sender_loop(self, ws: Any, state: _ConnectionState) -> None:
        try:
            while True:
                message = await state.queue.get()
                try:
                    await ws.send_text(message.payload)
                except asyncio.CancelledError:
                    if message.delivered is not None and not message.delivered.done():
                        message.delivered.cancel()
                    raise
                except Exception:
                    if message.delivered is not None and not message.delivered.done():
                        message.delivered.set_result(False)
                    logger.debug("ws_send_failed", exc_info=True)
                    break
                else:
                    if message.delivered is not None and not message.delivered.done():
                        message.delivered.set_result(True)
                finally:
                    state.queue.task_done()
        except asyncio.CancelledError:
            raise
        finally:
            while True:
                try:
                    pending = state.queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if pending.delivered is not None and not pending.delivered.done():
                    pending.delivered.set_result(False)
                state.queue.task_done()
            async with self._lock:
                current_state = self._connections.get(ws)
                if current_state is state:
                    self._remove_ws_unlocked(ws)

    def _publish_sse_event(
        self,
        queue: asyncio.Queue[WorkflowEvent],
        event: WorkflowEvent,
        *,
        run_id: str,
    ) -> bool:
        try:
            queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            try:
                dropped_event = queue.get_nowait()
            except asyncio.QueueEmpty:
                logger.warning("sse_queue_full_without_buffered_event", run_id=run_id)
                return False

            logger.warning(
                "sse_queue_backpressure",
                run_id=run_id,
                dropped_event_type=dropped_event.event_type.value,
                replacement_event_type=event.event_type.value,
                queue_maxsize=queue.maxsize,
            )

            try:
                queue.put_nowait(event)
                return True
            except asyncio.QueueFull:
                logger.warning("sse_queue_still_full_after_drop", run_id=run_id)
                return False

    def _assign_event_id(
        self,
        snapshot: WorkflowRunSnapshot,
        event: WorkflowEvent,
    ) -> WorkflowEvent:
        snapshot.last_event_id += 1
        return replace(event, event_id=str(snapshot.last_event_id))

    def _replay_events_unlocked(
        self,
        run_id: str,
        after_event_id: str | None,
    ) -> list[WorkflowEvent]:
        cursor = _parse_event_cursor(after_event_id)
        if cursor is None:
            return []
        buffer = self._sse_replay_buffers.get(run_id)
        if buffer is None:
            return []
        replay_events: list[WorkflowEvent] = []
        for event in buffer:
            event_cursor = _parse_event_cursor(event.event_id)
            if event_cursor is not None and event_cursor > cursor:
                replay_events.append(event)
        return replay_events


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_event_cursor(value: str | None) -> int | None:
    if value is None:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    try:
        parsed = int(candidate)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None
