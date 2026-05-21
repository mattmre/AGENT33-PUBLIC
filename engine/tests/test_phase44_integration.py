"""Integration tests for Phase 44: end-to-end session lifecycle with hooks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from agent33.hooks.models import HookContext, HookEventType
from agent33.hooks.protocol import BaseHook
from agent33.hooks.registry import HookRegistry
from agent33.sessions.models import (
    OperatorSessionStatus,
    SessionEvent,
    SessionEventType,
)
from agent33.sessions.service import OperatorSessionService
from agent33.sessions.storage import FileSessionStorage


class _TrackingHook(BaseHook):
    """Test hook that records all invocations."""

    def __init__(self, name: str, event_type: str) -> None:
        super().__init__(name=name, event_type=event_type, priority=100)
        self.calls: list[dict[str, Any]] = []

    async def execute(
        self,
        context: HookContext,
        call_next: Any,
    ) -> HookContext:
        self.calls.append(
            {
                "event_type": context.event_type,
                "tenant_id": context.tenant_id,
                "metadata": dict(context.metadata),
            }
        )
        return await call_next(context)


def _make_service_with_hooks(
    tmp_path: Path,
) -> tuple[OperatorSessionService, dict[str, _TrackingHook]]:
    """Create a service with tracking hooks for all session events."""
    registry = HookRegistry(max_per_event=20)
    hooks: dict[str, _TrackingHook] = {}
    for event_type in [
        HookEventType.SESSION_START,
        HookEventType.SESSION_END,
        HookEventType.SESSION_CHECKPOINT,
        HookEventType.SESSION_RESUME,
    ]:
        hook = _TrackingHook(f"tracker.{event_type}", event_type.value)
        registry.register(hook)
        hooks[event_type.value] = hook

    storage = FileSessionStorage(base_dir=tmp_path)
    svc = OperatorSessionService(
        storage=storage,
        hook_registry=registry,
        max_sessions_retained=50,
    )
    return svc, hooks


class TestEndToEndSessionLifecycle:
    """Full lifecycle: create -> tasks -> checkpoint -> end -> verify."""

    async def test_full_session_lifecycle(self, tmp_path: Path) -> None:
        svc, hooks = _make_service_with_hooks(tmp_path)

        # 1. Start session
        session = await svc.start_session(purpose="Integration test")
        assert hooks["session.start"].calls
        assert session.status == OperatorSessionStatus.ACTIVE

        # 2. Add tasks
        t1 = await svc.add_task(session.session_id, "Task A")
        t2 = await svc.add_task(session.session_id, "Task B")
        await svc.add_task(session.session_id, "Task C")

        # 3. Update tasks
        await svc.update_task(session.session_id, t1.task_id, "done")
        await svc.update_task(session.session_id, t2.task_id, "in_progress")

        # 4. Append custom events
        await svc.append_event(
            session.session_id,
            SessionEvent(
                event_type=SessionEventType.TOOL_EXECUTED,
                data={"tool": "shell", "command": "ls"},
            ),
        )
        await svc.append_event(
            session.session_id,
            SessionEvent(
                event_type=SessionEventType.AGENT_INVOKED,
                data={"agent": "code-worker"},
            ),
        )

        # 5. Checkpoint
        await svc.checkpoint(session.session_id)
        assert hooks["session.checkpoint"].calls

        # 6. Verify replay
        events = await svc.get_replay(session.session_id, offset=0, limit=100)
        event_types = [e.event_type for e in events]
        assert SessionEventType.SESSION_STARTED in event_types
        assert SessionEventType.TASK_ADDED in event_types
        assert SessionEventType.TASK_UPDATED in event_types
        assert SessionEventType.TOOL_EXECUTED in event_types
        assert SessionEventType.AGENT_INVOKED in event_types
        assert SessionEventType.CHECKPOINT in event_types

        # 7. Replay summary
        summary = await svc.get_replay_summary(session.session_id)
        # start + 3 task-adds + 2 updates + 2 custom + 1 checkpoint
        assert summary["total_events"] >= 7

        # 8. End session
        ended = await svc.end_session(session.session_id)
        assert ended.status == OperatorSessionStatus.COMPLETED
        assert ended.ended_at is not None
        assert hooks["session.end"].calls

        # 9. Verify task summary
        assert "1/3 done" in ended.task_summary

        # 10. Verify persisted on filesystem
        loaded = svc.storage.load_session(session.session_id)
        assert loaded is not None
        assert loaded.status == OperatorSessionStatus.COMPLETED


class TestCrashAndResumeCycle:
    """Test crash detection and session resume flow."""

    async def test_crash_detect_and_resume(self, tmp_path: Path) -> None:
        svc, hooks = _make_service_with_hooks(tmp_path)

        # Start session
        session = await svc.start_session(
            purpose="Will crash",
            context={"important_state": "preserve_me"},
        )
        await svc.add_task(session.session_id, "Unfinished task")
        await svc.checkpoint(session.session_id)

        # Simulate crash: write dead PID lock
        import json

        lock_file = tmp_path / session.session_id / "process.lock"
        lock_data = {"pid": 999999999, "started_at": "2026-01-01", "hostname": "test"}
        lock_file.write_text(json.dumps(lock_data))

        # Clear in-memory state (simulates process restart)
        svc._active.clear()

        # Detect crash
        crashed = await svc.detect_incomplete_sessions()
        assert len(crashed) == 1
        assert crashed[0].status == OperatorSessionStatus.CRASHED

        # Resume
        resumed = await svc.resume_session(session.session_id)
        assert resumed.status == OperatorSessionStatus.ACTIVE
        assert resumed.purpose == "Will crash"
        assert resumed.context.get("important_state") == "preserve_me"
        assert hooks["session.resume"].calls

        # Verify tasks survived
        tasks = await svc.list_tasks(session.session_id)
        assert len(tasks) == 1
        assert tasks[0].description == "Unfinished task"

        # End the resumed session
        ended = await svc.end_session(session.session_id)
        assert ended.status == OperatorSessionStatus.COMPLETED


class TestConcurrentSessions:
    """Test that multiple sessions do not interfere."""

    async def test_two_concurrent_sessions(self, tmp_path: Path) -> None:
        svc, _ = _make_service_with_hooks(tmp_path)

        s1 = await svc.start_session(purpose="Session 1")
        s2 = await svc.start_session(purpose="Session 2")

        await svc.add_task(s1.session_id, "S1 Task")
        await svc.add_task(s2.session_id, "S2 Task")

        tasks1 = await svc.list_tasks(s1.session_id)
        tasks2 = await svc.list_tasks(s2.session_id)

        assert len(tasks1) == 1
        assert tasks1[0].description == "S1 Task"
        assert len(tasks2) == 1
        assert tasks2[0].description == "S2 Task"

        # End one, verify the other continues
        await svc.end_session(s1.session_id)
        s2_loaded = await svc.get_session(s2.session_id)
        assert s2_loaded is not None
        assert s2_loaded.status == OperatorSessionStatus.ACTIVE

        await svc.end_session(s2.session_id)


class TestSessionCleanupIntegration:
    """Test session retention and cleanup."""

    async def test_cleanup_respects_max_retained(self, tmp_path: Path) -> None:
        storage = FileSessionStorage(base_dir=tmp_path)
        svc = OperatorSessionService(
            storage=storage,
            max_sessions_retained=3,
        )

        # Create 5 sessions
        for i in range(5):
            s = await svc.start_session(purpose=f"Session {i}")
            await svc.end_session(s.session_id)

        # Cleanup
        removed = await svc.cleanup_old_sessions()
        assert removed == 2
        remaining = storage.list_session_ids()
        assert len(remaining) == 3


class TestExistingHooksNonRegression:
    """Verify that existing hook functionality is not broken by Phase 44 changes."""

    def test_existing_event_types_still_work(self) -> None:
        """All pre-Phase-44 event types are still valid."""
        existing = [
            HookEventType.AGENT_INVOKE_PRE,
            HookEventType.AGENT_INVOKE_POST,
            HookEventType.TOOL_EXECUTE_PRE,
            HookEventType.TOOL_EXECUTE_POST,
            HookEventType.WORKFLOW_STEP_PRE,
            HookEventType.WORKFLOW_STEP_POST,
            HookEventType.REQUEST_PRE,
            HookEventType.REQUEST_POST,
        ]
        for et in existing:
            assert isinstance(et, HookEventType)

    def test_registry_builtin_discovery_includes_session_events(self) -> None:
        """discover_builtins() should register hooks for session events too."""
        registry = HookRegistry(max_per_event=30)
        count = registry.discover_builtins()
        # 12 event types x 2 builtins = 24
        assert count == 24

        # Verify session events have builtins
        session_hooks = registry.get_hooks(HookEventType.SESSION_START.value)
        assert len(session_hooks) == 2  # MetricsHook + AuditLogHook

    async def test_existing_hook_chain_runner_with_session_events(self) -> None:
        """HookChainRunner works with session event types."""
        from agent33.hooks.chain import HookChainRunner

        hook = _TrackingHook("test", HookEventType.SESSION_START.value)
        runner = HookChainRunner(hooks=[hook], timeout_ms=1000)

        ctx = HookContext(
            event_type=HookEventType.SESSION_START.value,
            tenant_id="t1",
            metadata={"session_id": "s1"},
        )
        result = await runner.run(ctx)
        assert len(result.results) == 1
        assert result.results[0].success
        assert hook.calls[0]["event_type"] == "session.start"
