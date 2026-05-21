"""Operator session service: lifecycle, persistence, replay, crash detection."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from agent33.sessions.models import (
    OperatorSession,
    OperatorSessionStatus,
    SessionEvent,
    SessionEventType,
    TaskEntry,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from agent33.sessions.storage import FileSessionStorage

logger = logging.getLogger(__name__)


class OperatorSessionService:
    """Manages operator session lifecycle, persistence, and replay logging.

    This service owns the durable session state. It is separate from the
    existing SessionManager (which handles encrypted runtime sessions for
    agent conversations).
    """

    def __init__(
        self,
        storage: FileSessionStorage,
        hook_registry: Any | None = None,
        checkpoint_interval_seconds: float = 60.0,
        max_sessions_retained: int = 100,
        session_cleanup_callback: Callable[[str], None] | None = None,
    ) -> None:
        self._storage = storage
        self._hook_registry = hook_registry
        self._checkpoint_interval = checkpoint_interval_seconds
        self._max_retained = max_sessions_retained
        self._session_cleanup_callback = session_cleanup_callback
        # In-memory cache of active sessions for fast lookup
        self._active: dict[str, OperatorSession] = {}
        self._status_snapshot_builder: (
            Callable[[OperatorSession], Awaitable[dict[str, Any]]] | None
        ) = None

    @property
    def storage(self) -> FileSessionStorage:
        return self._storage

    def set_status_snapshot_builder(
        self,
        builder: Callable[[OperatorSession], Awaitable[dict[str, Any]]] | None,
    ) -> None:
        """Attach or clear the status-line snapshot builder."""
        self._status_snapshot_builder = builder

    def clear_terminal_session_state(self, session_id: str) -> None:
        """Run any terminal lifecycle cleanup registered for the session."""
        if self._session_cleanup_callback is not None:
            try:
                self._session_cleanup_callback(session_id)
            except Exception:
                logger.warning(
                    "session_cleanup_callback_failed session_id=%s",
                    session_id,
                    exc_info=True,
                )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start_session(
        self,
        purpose: str = "",
        context: dict[str, Any] | None = None,
        tenant_id: str = "",
    ) -> OperatorSession:
        """Create a new operator session.

        1. Generate sanitized session_id (UUID hex)
        2. Create filesystem directory structure
        3. Write initial session.json
        4. Fire session.start hooks
        """
        session_id = uuid4().hex
        now = datetime.now(UTC)
        session = OperatorSession(
            session_id=session_id,
            purpose=purpose,
            status=OperatorSessionStatus.ACTIVE,
            started_at=now,
            updated_at=now,
            tenant_id=tenant_id,
            context=context or {},
        )
        self._storage.ensure_base_dir()
        self._storage.save_session(session)
        self._storage.write_lock(session_id)

        # Log the start event
        event = SessionEvent(
            event_type=SessionEventType.SESSION_STARTED,
            session_id=session_id,
            data={"purpose": purpose},
        )
        self._storage.append_event(session_id, event)
        session.event_count = 1
        await self._refresh_status_cache(session)
        self._storage.save_session(session)

        self._active[session_id] = session

        # Fire session.start hooks
        await self._fire_hooks("session.start", session)

        logger.info(
            "session_started session_id=%s purpose=%s",
            session_id,
            purpose[:80] if purpose else "(none)",
        )
        return session

    async def end_session(
        self,
        session_id: str,
        status: OperatorSessionStatus = OperatorSessionStatus.COMPLETED,
    ) -> OperatorSession:
        """End an operator session.

        1. Update status and ended_at
        2. Fire session.end hooks
        3. Flush final checkpoint
        4. Remove process lock

        Raises:
            KeyError: If the session is not found.
            ValueError: If the session is not in an endable state.
        """
        session = await self.get_session(session_id)
        if session is None:
            raise KeyError(f"Session {session_id} not found")
        if session.status not in (
            OperatorSessionStatus.ACTIVE,
            OperatorSessionStatus.SUSPENDED,
        ):
            raise ValueError(
                f"Cannot end session in status '{session.status}'; "
                f"expected 'active' or 'suspended'"
            )
        if status not in (OperatorSessionStatus.COMPLETED, OperatorSessionStatus.SUSPENDED):
            raise ValueError(f"End status must be 'completed' or 'suspended', got '{status}'")

        now = datetime.now(UTC)
        session.status = status
        session.ended_at = now
        session.updated_at = now

        # Update task summary
        session.task_summary = self._build_task_summary(session)

        # Log the end event
        event = SessionEvent(
            event_type=SessionEventType.SESSION_ENDED,
            session_id=session_id,
            data={"status": status.value, "task_summary": session.task_summary},
        )
        self._storage.append_event(session_id, event)
        session.event_count = self._storage.event_count(session_id)
        await self._refresh_status_cache(session)

        # Fire hooks, save, clean up
        await self._fire_hooks("session.end", session)
        self._storage.save_session(session)
        self._storage.save_checkpoint(session)
        self._storage.remove_lock(session_id)

        self._active.pop(session_id, None)
        if status == OperatorSessionStatus.COMPLETED:
            self.clear_terminal_session_state(session_id)

        logger.info(
            "session_ended session_id=%s status=%s",
            session_id,
            status.value,
        )
        return session

    async def resume_session(self, session_id: str) -> OperatorSession:
        """Resume a previously incomplete session.

        1. Load session from filesystem
        2. Validate status is CRASHED or SUSPENDED
        3. Update status to ACTIVE
        4. Fire session.resume hooks

        Raises:
            KeyError: If the session is not found.
            ValueError: If the session is not resumable.
        """
        session = await self.get_session(session_id)
        if session is None:
            raise KeyError(f"Session {session_id} not found")
        if session.status not in (
            OperatorSessionStatus.CRASHED,
            OperatorSessionStatus.SUSPENDED,
        ):
            raise ValueError(
                f"Cannot resume session in status '{session.status}'; "
                f"expected 'crashed' or 'suspended'"
            )

        now = datetime.now(UTC)
        session.status = OperatorSessionStatus.ACTIVE
        session.updated_at = now
        session.ended_at = None

        # Log the resume event
        event = SessionEvent(
            event_type=SessionEventType.SESSION_RESUMED,
            session_id=session_id,
            data={"previous_status": session.status.value},
        )
        self._storage.append_event(session_id, event)
        session.event_count = self._storage.event_count(session_id)
        await self._refresh_status_cache(session)

        self._storage.save_session(session)
        self._storage.write_lock(session_id)
        self._active[session_id] = session

        await self._fire_hooks("session.resume", session)

        logger.info("session_resumed session_id=%s", session_id)
        return session

    async def checkpoint(self, session_id: str) -> None:
        """Periodic state flush.

        1. Write checkpoint.json with current state
        2. Fire session.checkpoint hooks
        3. Rotate replay log if needed
        """
        session = await self.get_session(session_id)
        if session is None:
            raise KeyError(f"Session {session_id} not found")

        now = datetime.now(UTC)
        session.last_checkpoint_at = now
        session.updated_at = now
        session.event_count = self._storage.event_count(session_id)
        session.task_summary = self._build_task_summary(session)

        # Log checkpoint event
        event = SessionEvent(
            event_type=SessionEventType.CHECKPOINT,
            session_id=session_id,
            data={"event_count": session.event_count},
        )
        self._storage.append_event(session_id, event)
        session.event_count = self._storage.event_count(session_id)
        await self._refresh_status_cache(session)

        self._storage.save_session(session)
        self._storage.save_checkpoint(session)
        self._storage.rotate_replay_log(session_id)

        if session_id in self._active:
            self._active[session_id] = session

        await self._fire_hooks("session.checkpoint", session)

        logger.debug("session_checkpoint session_id=%s", session_id)

    # ------------------------------------------------------------------
    # Task tracking
    # ------------------------------------------------------------------

    async def add_task(
        self, session_id: str, description: str, metadata: dict[str, Any] | None = None
    ) -> TaskEntry:
        """Add a task to the session."""
        session = await self.get_session(session_id)
        if session is None:
            raise KeyError(f"Session {session_id} not found")

        task = TaskEntry(
            description=description,
            metadata=metadata or {},
        )
        session.tasks.append(task)
        session.updated_at = datetime.now(UTC)
        self._storage.save_session(session)

        event = SessionEvent(
            event_type=SessionEventType.TASK_ADDED,
            session_id=session_id,
            data={"task_id": task.task_id, "description": description},
        )
        self._storage.append_event(session_id, event)

        if session_id in self._active:
            self._active[session_id] = session
        return task

    async def update_task(
        self,
        session_id: str,
        task_id: str,
        status: str,
    ) -> TaskEntry:
        """Update a task's status.

        Raises:
            KeyError: If the session or task is not found.
            ValueError: If the status is invalid.
        """
        valid_statuses = {"pending", "in_progress", "done", "blocked"}
        if status not in valid_statuses:
            raise ValueError(f"Invalid task status: {status}")

        session = await self.get_session(session_id)
        if session is None:
            raise KeyError(f"Session {session_id} not found")

        task = None
        for t in session.tasks:
            if t.task_id == task_id:
                task = t
                break
        if task is None:
            raise KeyError(f"Task {task_id} not found in session {session_id}")

        task.status = status  # type: ignore[assignment]
        if status == "done":
            task.completed_at = datetime.now(UTC)
        session.updated_at = datetime.now(UTC)
        self._storage.save_session(session)

        event = SessionEvent(
            event_type=SessionEventType.TASK_UPDATED,
            session_id=session_id,
            data={"task_id": task_id, "status": status},
        )
        self._storage.append_event(session_id, event)

        if session_id in self._active:
            self._active[session_id] = session
        return task

    async def list_tasks(self, session_id: str) -> list[TaskEntry]:
        """List all tasks for a session."""
        session = await self.get_session(session_id)
        if session is None:
            raise KeyError(f"Session {session_id} not found")
        return list(session.tasks)

    # ------------------------------------------------------------------
    # Replay
    # ------------------------------------------------------------------

    async def append_event(self, session_id: str, event: SessionEvent) -> None:
        """Append an event to the replay log."""
        event.session_id = session_id
        self._storage.append_event(session_id, event)
        session = self._active.get(session_id)
        if session is not None:
            session.event_count = self._storage.event_count(session_id)

    async def get_replay(
        self,
        session_id: str,
        offset: int = 0,
        limit: int = 100,
    ) -> list[SessionEvent]:
        """Read events from the replay log with pagination."""
        return self._storage.read_events(session_id, offset=offset, limit=limit)

    async def get_replay_summary(self, session_id: str) -> dict[str, Any]:
        """Generate a summary of the replay log for the session."""
        events = self._storage.read_events(session_id, offset=0, limit=10000)
        if not events:
            return {"total_events": 0, "by_type": {}, "duration_seconds": 0.0}

        by_type: dict[str, int] = {}
        for ev in events:
            key = ev.event_type.value
            by_type[key] = by_type.get(key, 0) + 1

        first_ts = events[0].timestamp
        last_ts = events[-1].timestamp
        duration = (last_ts - first_ts).total_seconds()

        return {
            "total_events": len(events),
            "by_type": by_type,
            "duration_seconds": round(duration, 2),
            "first_event_at": first_ts.isoformat(),
            "last_event_at": last_ts.isoformat(),
        }

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    async def get_session(self, session_id: str) -> OperatorSession | None:
        """Get a session by ID (from memory cache or filesystem)."""
        if session_id in self._active:
            return self._active[session_id]
        return self._storage.load_session(session_id)

    async def list_sessions(
        self,
        status: OperatorSessionStatus | None = None,
        limit: int = 50,
        tenant_id: str | None = None,
    ) -> list[OperatorSession]:
        """List sessions with optional status filter."""
        return self._storage.list_sessions(status=status, limit=limit, tenant_id=tenant_id)

    # ------------------------------------------------------------------
    # Crash detection
    # ------------------------------------------------------------------

    async def detect_incomplete_sessions(
        self,
        tenant_id: str | None = None,
    ) -> list[OperatorSession]:
        """Scan for sessions with status=ACTIVE that have no live process.

        A session is considered crashed if:
        - status is ACTIVE
        - No process lock file is held, or the PID is dead

        Returns sessions marked as CRASHED (status is updated).
        """
        crashed: list[OperatorSession] = []
        for sid in self._storage.list_session_ids():
            session = self._storage.load_session(sid)
            if session is None:
                continue
            if tenant_id is not None and session.tenant_id != tenant_id:
                continue
            if session.status != OperatorSessionStatus.ACTIVE:
                continue
            # Check if process is still alive
            if self._storage.is_process_alive(sid):
                continue
            # Mark as crashed
            session.status = OperatorSessionStatus.CRASHED
            session.updated_at = datetime.now(UTC)
            self._storage.save_session(session)
            self._storage.remove_lock(sid)
            crashed.append(session)
            logger.warning(
                "incomplete_session_detected session_id=%s purpose=%s",
                sid,
                session.purpose[:80] if session.purpose else "(none)",
            )
        return crashed

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    async def cleanup_old_sessions(self) -> int:
        """Remove sessions beyond max_sessions_retained."""
        return self._storage.cleanup_old_sessions(self._max_retained)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def shutdown(self) -> None:
        """Flush active sessions on shutdown.

        Active sessions get a final checkpoint and their locks are removed.
        This is called during application shutdown to leave sessions in a
        clean state.
        """
        for session_id, session in list(self._active.items()):
            try:
                session.updated_at = datetime.now(UTC)
                session.last_checkpoint_at = datetime.now(UTC)
                session.event_count = self._storage.event_count(session_id)
                self._storage.save_session(session)
                self._storage.save_checkpoint(session)
                self._storage.remove_lock(session_id)
            except Exception:
                logger.warning(
                    "session_shutdown_flush_failed session_id=%s",
                    session_id,
                    exc_info=True,
                )
        self._active.clear()
        logger.info("operator_session_service_shutdown")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fire_hooks(self, event_type: str, session: OperatorSession) -> None:
        """Fire hooks for the given session event type."""
        if self._hook_registry is None:
            return
        try:
            from agent33.hooks.models import HookContext

            ctx = HookContext(
                event_type=event_type,
                tenant_id=session.tenant_id,
                metadata={
                    "session_id": session.session_id,
                    "session_base_dir": str(self._storage.base_dir),
                    "purpose": session.purpose,
                    "status": session.status.value,
                },
            )
            runner = self._hook_registry.get_chain_runner(
                event_type,
                tenant_id=session.tenant_id,
            )
            await runner.run(ctx)
        except Exception:
            logger.warning(
                "session_hook_fire_failed event=%s session=%s",
                event_type,
                session.session_id,
                exc_info=True,
            )

    async def _refresh_status_cache(self, session: OperatorSession) -> None:
        """Update the persisted status-line cache when a builder is configured."""
        if self._status_snapshot_builder is None:
            return
        try:
            session.cache["status_line"] = await self._status_snapshot_builder(session)
        except Exception:
            logger.warning(
                "status_snapshot_refresh_failed session_id=%s",
                session.session_id,
                exc_info=True,
            )

    @staticmethod
    def _build_task_summary(session: OperatorSession) -> str:
        """Generate a human-readable task summary."""
        total = len(session.tasks)
        if total == 0:
            return "No tasks tracked"
        done = sum(1 for t in session.tasks if t.status == "done")
        in_progress = sum(1 for t in session.tasks if t.status == "in_progress")
        blocked = sum(1 for t in session.tasks if t.status == "blocked")
        pending = total - done - in_progress - blocked
        parts: list[str] = [f"{done}/{total} done"]
        if in_progress:
            parts.append(f"{in_progress} in progress")
        if blocked:
            parts.append(f"{blocked} blocked")
        if pending:
            parts.append(f"{pending} pending")
        return ", ".join(parts)
