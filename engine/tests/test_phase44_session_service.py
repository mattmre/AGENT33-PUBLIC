"""Tests for Phase 44 OperatorSessionService: lifecycle, tasks, replay, crash detection."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent33.sessions.models import (
    OperatorSessionStatus,
    SessionEvent,
    SessionEventType,
)
from agent33.sessions.service import OperatorSessionService
from agent33.sessions.storage import FileSessionStorage


def _make_service(
    tmp_path: Path,
    hook_registry: Any = None,
    session_cleanup_callback: Any = None,
) -> OperatorSessionService:
    """Helper to create a service with file storage."""
    storage = FileSessionStorage(base_dir=tmp_path)
    return OperatorSessionService(
        storage=storage,
        hook_registry=hook_registry,
        checkpoint_interval_seconds=60.0,
        max_sessions_retained=100,
        session_cleanup_callback=session_cleanup_callback,
    )


class TestSessionLifecycle:
    """Tests for session start/end/resume."""

    async def test_start_session_creates_active_session(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session(purpose="Build feature X")

        assert session.status == OperatorSessionStatus.ACTIVE
        assert session.purpose == "Build feature X"
        assert session.session_id  # non-empty
        assert session.event_count >= 1  # at least the start event

    async def test_start_session_persists_to_filesystem(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session(purpose="Persist test")

        # Verify filesystem
        session_file = tmp_path / session.session_id / "session.json"
        assert session_file.exists()

        # Verify replay log has start event
        events = svc.storage.read_events(session.session_id)
        assert len(events) >= 1
        assert events[0].event_type == SessionEventType.SESSION_STARTED

    async def test_start_session_writes_process_lock(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session()
        lock = svc.storage.read_lock(session.session_id)
        assert lock is not None
        assert "pid" in lock

    async def test_start_session_with_context(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session(
            purpose="Ctx test",
            context={"branch": "main", "task_count": 3},
        )
        assert session.context["branch"] == "main"
        assert session.context["task_count"] == 3

    async def test_end_session_completed(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session(purpose="End test")
        ended = await svc.end_session(session.session_id)

        assert ended.status == OperatorSessionStatus.COMPLETED
        assert ended.ended_at is not None
        # Lock should be removed
        assert svc.storage.read_lock(session.session_id) is None

    async def test_end_session_completed_clears_terminal_session_state(
        self, tmp_path: Path
    ) -> None:
        cleanup = MagicMock()
        svc = _make_service(tmp_path, session_cleanup_callback=cleanup)
        session = await svc.start_session(purpose="End cleanup test")

        await svc.end_session(session.session_id)

        cleanup.assert_called_once_with(session.session_id)

    async def test_end_session_completed_logs_cleanup_failure_and_continues(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        def cleanup_callback(_: str) -> None:
            raise RuntimeError("cleanup failed")

        svc = _make_service(tmp_path, session_cleanup_callback=cleanup_callback)
        session = await svc.start_session(purpose="End cleanup failure test")

        with caplog.at_level(logging.WARNING):
            ended = await svc.end_session(session.session_id)

        assert ended.status == OperatorSessionStatus.COMPLETED
        assert "session_cleanup_callback_failed" in caplog.text

    async def test_end_session_suspended(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session()
        ended = await svc.end_session(
            session.session_id,
            status=OperatorSessionStatus.SUSPENDED,
        )
        assert ended.status == OperatorSessionStatus.SUSPENDED

    async def test_end_session_suspended_preserves_terminal_session_state(
        self, tmp_path: Path
    ) -> None:
        cleanup = MagicMock()
        svc = _make_service(tmp_path, session_cleanup_callback=cleanup)
        session = await svc.start_session()

        await svc.end_session(
            session.session_id,
            status=OperatorSessionStatus.SUSPENDED,
        )

        cleanup.assert_not_called()

    async def test_end_session_logs_end_event(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session()
        await svc.end_session(session.session_id)

        events = svc.storage.read_events(session.session_id)
        end_events = [e for e in events if e.event_type == SessionEventType.SESSION_ENDED]
        assert len(end_events) == 1

    async def test_end_nonexistent_session_raises(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        with pytest.raises(KeyError):
            await svc.end_session("nonexistent")

    async def test_end_already_completed_session_raises(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session()
        await svc.end_session(session.session_id)
        with pytest.raises(ValueError, match="Cannot end session"):
            await svc.end_session(session.session_id)

    async def test_end_session_with_invalid_status_raises(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session()
        with pytest.raises(ValueError, match="End status must be"):
            await svc.end_session(
                session.session_id,
                status=OperatorSessionStatus.CRASHED,
            )

    async def test_resume_crashed_session(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session(purpose="Resume test")

        # Simulate crash
        session.status = OperatorSessionStatus.CRASHED
        svc.storage.save_session(session)
        svc._active.pop(session.session_id, None)

        resumed = await svc.resume_session(session.session_id)
        assert resumed.status == OperatorSessionStatus.ACTIVE
        assert resumed.purpose == "Resume test"

    async def test_resume_suspended_session(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session()
        await svc.end_session(
            session.session_id,
            status=OperatorSessionStatus.SUSPENDED,
        )
        resumed = await svc.resume_session(session.session_id)
        assert resumed.status == OperatorSessionStatus.ACTIVE

    async def test_resume_active_session_raises(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session()
        with pytest.raises(ValueError, match="Cannot resume"):
            await svc.resume_session(session.session_id)

    async def test_resume_nonexistent_raises(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        with pytest.raises(KeyError):
            await svc.resume_session("nope")

    async def test_resume_logs_event(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session()
        session.status = OperatorSessionStatus.CRASHED
        svc.storage.save_session(session)
        svc._active.pop(session.session_id, None)

        await svc.resume_session(session.session_id)
        events = svc.storage.read_events(session.session_id)
        resume_events = [e for e in events if e.event_type == SessionEventType.SESSION_RESUMED]
        assert len(resume_events) == 1


class TestSessionCheckpoint:
    """Tests for checkpoint operations."""

    async def test_checkpoint_updates_state(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session()
        await svc.checkpoint(session.session_id)

        updated = await svc.get_session(session.session_id)
        assert updated is not None
        assert updated.last_checkpoint_at is not None

    async def test_checkpoint_saves_checkpoint_file(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session()
        await svc.checkpoint(session.session_id)

        cp_file = tmp_path / session.session_id / "checkpoint.json"
        assert cp_file.exists()

    async def test_checkpoint_logs_event(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session()
        await svc.checkpoint(session.session_id)

        events = svc.storage.read_events(session.session_id)
        cp_events = [e for e in events if e.event_type == SessionEventType.CHECKPOINT]
        assert len(cp_events) == 1

    async def test_checkpoint_nonexistent_raises(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        with pytest.raises(KeyError):
            await svc.checkpoint("nope")

    async def test_checkpoint_refreshes_status_line_cache(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        svc.set_status_snapshot_builder(
            AsyncMock(return_value={"rendered": "main@abc123 | tools:0 voice:ok"})
        )
        session = await svc.start_session()

        await svc.checkpoint(session.session_id)

        updated = await svc.get_session(session.session_id)
        assert updated is not None
        assert updated.cache["status_line"]["rendered"] == "main@abc123 | tools:0 voice:ok"


class TestTaskTracking:
    """Tests for task CRUD within sessions."""

    async def test_add_task(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session()
        task = await svc.add_task(session.session_id, "Implement feature A")

        assert task.description == "Implement feature A"
        assert task.status == "pending"
        assert task.task_id  # non-empty

    async def test_update_task_to_done(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session()
        task = await svc.add_task(session.session_id, "Task B")
        updated = await svc.update_task(session.session_id, task.task_id, "done")

        assert updated.status == "done"
        assert updated.completed_at is not None

    async def test_update_task_invalid_status_raises(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session()
        task = await svc.add_task(session.session_id, "Task C")
        with pytest.raises(ValueError, match="Invalid task status"):
            await svc.update_task(session.session_id, task.task_id, "invalid_status")

    async def test_update_nonexistent_task_raises(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session()
        with pytest.raises(KeyError, match="Task .* not found"):
            await svc.update_task(session.session_id, "no_such_task", "done")

    async def test_list_tasks(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session()
        await svc.add_task(session.session_id, "Task 1")
        await svc.add_task(session.session_id, "Task 2")

        tasks = await svc.list_tasks(session.session_id)
        assert len(tasks) == 2
        descriptions = {t.description for t in tasks}
        assert descriptions == {"Task 1", "Task 2"}

    async def test_add_task_logs_event(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session()
        await svc.add_task(session.session_id, "Logged task")

        events = svc.storage.read_events(session.session_id)
        task_events = [e for e in events if e.event_type == SessionEventType.TASK_ADDED]
        assert len(task_events) == 1
        assert task_events[0].data["description"] == "Logged task"

    async def test_update_task_logs_event(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session()
        task = await svc.add_task(session.session_id, "Update logged")
        await svc.update_task(session.session_id, task.task_id, "in_progress")

        events = svc.storage.read_events(session.session_id)
        upd_events = [e for e in events if e.event_type == SessionEventType.TASK_UPDATED]
        assert len(upd_events) == 1
        assert upd_events[0].data["status"] == "in_progress"

    async def test_add_task_with_metadata(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session()
        task = await svc.add_task(
            session.session_id,
            "Meta task",
            metadata={"priority": "high", "estimate_hours": 4},
        )
        assert task.metadata["priority"] == "high"
        assert task.metadata["estimate_hours"] == 4


class TestReplay:
    """Tests for replay log operations."""

    async def test_append_and_get_replay(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session()

        for i in range(5):
            event = SessionEvent(
                event_type=SessionEventType.TOOL_EXECUTED,
                data={"tool": f"tool_{i}"},
            )
            await svc.append_event(session.session_id, event)

        events = await svc.get_replay(session.session_id)
        tool_events = [e for e in events if e.event_type == SessionEventType.TOOL_EXECUTED]
        assert len(tool_events) == 5

    async def test_get_replay_with_pagination(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session()

        for i in range(20):
            await svc.append_event(
                session.session_id,
                SessionEvent(
                    event_type=SessionEventType.AGENT_INVOKED,
                    data={"index": i},
                ),
            )

        page = await svc.get_replay(session.session_id, offset=5, limit=3)
        assert len(page) == 3

    async def test_get_replay_summary(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session()

        await svc.append_event(
            session.session_id,
            SessionEvent(event_type=SessionEventType.TOOL_EXECUTED),
        )
        await svc.append_event(
            session.session_id,
            SessionEvent(event_type=SessionEventType.TOOL_EXECUTED),
        )
        await svc.append_event(
            session.session_id,
            SessionEvent(event_type=SessionEventType.AGENT_INVOKED),
        )

        summary = await svc.get_replay_summary(session.session_id)
        assert summary["total_events"] >= 4  # start + 3 appended
        assert "by_type" in summary
        assert summary["duration_seconds"] >= 0.0


class TestCrashDetection:
    """Tests for incomplete session detection."""

    async def test_detect_crashed_session_with_dead_pid(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session(purpose="Crash me")

        # Simulate crash: write a lock with a dead PID
        import json

        lock_file = tmp_path / session.session_id / "process.lock"
        lock_data = {"pid": 999999999, "started_at": "2026-01-01T00:00:00", "hostname": "test"}
        lock_file.write_text(json.dumps(lock_data), encoding="utf-8")

        # Remove from active cache to simulate process restart
        svc._active.clear()

        crashed = await svc.detect_incomplete_sessions()
        assert len(crashed) == 1
        assert crashed[0].session_id == session.session_id
        assert crashed[0].status == OperatorSessionStatus.CRASHED

    async def test_detect_does_not_flag_live_process(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        await svc.start_session()
        # Lock has current PID, so it should be alive
        svc._active.clear()

        crashed = await svc.detect_incomplete_sessions()
        assert len(crashed) == 0

    async def test_detect_does_not_flag_completed_sessions(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session()
        await svc.end_session(session.session_id)
        svc._active.clear()

        crashed = await svc.detect_incomplete_sessions()
        assert len(crashed) == 0

    async def test_detect_incomplete_sessions_filters_by_tenant(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        tenant_a = await svc.start_session(purpose="Tenant A", tenant_id="tenant-a")
        tenant_b = await svc.start_session(purpose="Tenant B", tenant_id="tenant-b")

        import json

        for session in (tenant_a, tenant_b):
            lock_file = tmp_path / session.session_id / "process.lock"
            lock_data = {"pid": 999999999, "started_at": "2026-01-01T00:00:00", "hostname": "test"}
            lock_file.write_text(json.dumps(lock_data), encoding="utf-8")

        svc._active.clear()

        crashed = await svc.detect_incomplete_sessions(tenant_id="tenant-a")
        assert [session.session_id for session in crashed] == [tenant_a.session_id]

        untouched = await svc.get_session(tenant_b.session_id)
        assert untouched is not None
        assert untouched.status == OperatorSessionStatus.ACTIVE


class TestSessionQuery:
    """Tests for session querying."""

    async def test_get_session_from_cache(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session(purpose="Cached")
        loaded = await svc.get_session(session.session_id)
        assert loaded is not None
        assert loaded.purpose == "Cached"

    async def test_get_session_from_filesystem(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session(purpose="FS load")
        svc._active.clear()  # Clear cache

        loaded = await svc.get_session(session.session_id)
        assert loaded is not None
        assert loaded.purpose == "FS load"

    async def test_get_nonexistent_returns_none(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        assert await svc.get_session("nope") is None

    async def test_list_sessions(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        await svc.start_session(purpose="S1")
        await svc.start_session(purpose="S2")

        all_sessions = await svc.list_sessions()
        assert len(all_sessions) >= 2

    async def test_list_sessions_filters_by_tenant(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        await svc.start_session(purpose="Tenant A", tenant_id="tenant-a")
        await svc.start_session(purpose="Tenant B", tenant_id="tenant-b")

        tenant_a_sessions = await svc.list_sessions(tenant_id="tenant-a")
        assert len(tenant_a_sessions) == 1
        assert tenant_a_sessions[0].tenant_id == "tenant-a"


class TestSessionHookFiring:
    """Tests that hooks are fired during session lifecycle events."""

    async def test_start_session_fires_hooks(self, tmp_path: Path) -> None:
        mock_registry = MagicMock()
        mock_runner = AsyncMock()
        mock_runner.run = AsyncMock()
        mock_registry.get_chain_runner.return_value = mock_runner

        svc = _make_service(tmp_path, hook_registry=mock_registry)
        await svc.start_session(purpose="Hook test")

        mock_registry.get_chain_runner.assert_called_once()
        call_args = mock_registry.get_chain_runner.call_args
        assert call_args[0][0] == "session.start"

    async def test_end_session_fires_hooks(self, tmp_path: Path) -> None:
        mock_registry = MagicMock()
        mock_runner = AsyncMock()
        mock_runner.run = AsyncMock()
        mock_registry.get_chain_runner.return_value = mock_runner

        svc = _make_service(tmp_path, hook_registry=mock_registry)
        session = await svc.start_session()
        mock_registry.reset_mock()

        await svc.end_session(session.session_id)
        mock_registry.get_chain_runner.assert_called_once()
        call_args = mock_registry.get_chain_runner.call_args
        assert call_args[0][0] == "session.end"

    async def test_checkpoint_fires_hooks(self, tmp_path: Path) -> None:
        mock_registry = MagicMock()
        mock_runner = AsyncMock()
        mock_runner.run = AsyncMock()
        mock_registry.get_chain_runner.return_value = mock_runner

        svc = _make_service(tmp_path, hook_registry=mock_registry)
        session = await svc.start_session()
        mock_registry.reset_mock()

        await svc.checkpoint(session.session_id)
        mock_registry.get_chain_runner.assert_called_once()
        call_args = mock_registry.get_chain_runner.call_args
        assert call_args[0][0] == "session.checkpoint"

    async def test_hook_failure_does_not_break_session(self, tmp_path: Path) -> None:
        mock_registry = MagicMock()
        mock_runner = AsyncMock()
        mock_runner.run = AsyncMock(side_effect=RuntimeError("Hook exploded"))
        mock_registry.get_chain_runner.return_value = mock_runner

        svc = _make_service(tmp_path, hook_registry=mock_registry)
        # Should not raise despite hook failure
        session = await svc.start_session(purpose="Robust")
        assert session.status == OperatorSessionStatus.ACTIVE


class TestSessionShutdown:
    """Tests for graceful shutdown."""

    async def test_shutdown_flushes_active_sessions(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        s1 = await svc.start_session(purpose="Shutdown 1")
        await svc.start_session(purpose="Shutdown 2")
        assert len(svc._active) == 2

        await svc.shutdown()
        assert len(svc._active) == 0

        # Sessions should still be loadable from filesystem
        loaded = svc.storage.load_session(s1.session_id)
        assert loaded is not None
        # Lock should be removed
        assert svc.storage.read_lock(s1.session_id) is None


class TestTaskSummary:
    """Tests for auto-generated task summary."""

    async def test_task_summary_with_tasks(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session()
        await svc.add_task(session.session_id, "Task 1")
        await svc.add_task(session.session_id, "Task 2")
        t3 = await svc.add_task(session.session_id, "Task 3")
        await svc.update_task(session.session_id, t3.task_id, "done")

        await svc.end_session(session.session_id)
        ended = await svc.get_session(session.session_id)
        assert ended is not None
        assert "1/3 done" in ended.task_summary

    async def test_task_summary_no_tasks(self, tmp_path: Path) -> None:
        svc = _make_service(tmp_path)
        session = await svc.start_session()
        await svc.end_session(session.session_id)
        ended = await svc.get_session(session.session_id)
        assert ended is not None
        assert ended.task_summary == "No tasks tracked"
