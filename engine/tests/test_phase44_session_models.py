"""Tests for Phase 44 session models: OperatorSession, TaskEntry, SessionEvent."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent33.sessions.models import (
    OperatorSession,
    OperatorSessionStatus,
    SessionEvent,
    SessionEventType,
    TaskEntry,
)


class TestTaskEntry:
    """Tests for TaskEntry serialization and deserialization."""

    def test_default_task_has_pending_status(self) -> None:
        task = TaskEntry(description="Do something")
        assert task.status == "pending"
        assert task.completed_at is None
        assert task.task_id  # non-empty

    def test_to_dict_roundtrip(self) -> None:
        task = TaskEntry(
            task_id="abc123",
            description="Write tests",
            status="in_progress",
            metadata={"priority": "high"},
        )
        d = task.to_dict()
        assert d["task_id"] == "abc123"
        assert d["description"] == "Write tests"
        assert d["status"] == "in_progress"
        assert d["metadata"] == {"priority": "high"}

        restored = TaskEntry.from_dict(d)
        assert restored.task_id == "abc123"
        assert restored.description == "Write tests"
        assert restored.status == "in_progress"

    def test_from_dict_with_completed_at(self) -> None:
        now = datetime.now(UTC)
        d = {
            "task_id": "t1",
            "description": "Done task",
            "status": "done",
            "created_at": now.isoformat(),
            "completed_at": now.isoformat(),
            "metadata": {},
        }
        task = TaskEntry.from_dict(d)
        assert task.status == "done"
        assert task.completed_at is not None

    def test_from_dict_with_missing_fields_uses_defaults(self) -> None:
        task = TaskEntry.from_dict({})
        assert task.description == ""
        assert task.status == "pending"
        assert task.metadata == {}

    def test_from_dict_invalid_created_at_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Invalid created_at"):
            TaskEntry.from_dict({"created_at": "not-a-timestamp"})


class TestSessionEvent:
    """Tests for SessionEvent serialization."""

    def test_event_default_fields(self) -> None:
        event = SessionEvent(
            event_type=SessionEventType.SESSION_STARTED,
            session_id="abc",
            data={"foo": "bar"},
        )
        assert event.event_id  # auto-generated
        assert event.session_id == "abc"
        assert event.data == {"foo": "bar"}

    def test_to_dict_roundtrip(self) -> None:
        event = SessionEvent(
            event_id="evt1",
            event_type=SessionEventType.TASK_ADDED,
            session_id="s1",
            data={"task_id": "t1"},
            correlation_id="corr1",
        )
        d = event.to_dict()
        assert d["event_id"] == "evt1"
        assert d["event_type"] == "task.added"
        assert d["session_id"] == "s1"
        assert d["correlation_id"] == "corr1"

        restored = SessionEvent.from_dict(d)
        assert restored.event_id == "evt1"
        assert restored.event_type == SessionEventType.TASK_ADDED
        assert restored.session_id == "s1"

    def test_all_event_types_are_valid(self) -> None:
        """Verify all SessionEventType values can be used to create events."""
        for et in SessionEventType:
            event = SessionEvent(event_type=et, session_id="test")
            d = event.to_dict()
            restored = SessionEvent.from_dict(d)
            assert restored.event_type == et

    def test_from_dict_invalid_timestamp_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Invalid timestamp"):
            SessionEvent.from_dict({"event_type": "session.started", "timestamp": "bad"})


class TestOperatorSession:
    """Tests for OperatorSession serialization and properties."""

    def test_default_session_is_active(self) -> None:
        session = OperatorSession(purpose="Build feature")
        assert session.status == OperatorSessionStatus.ACTIVE
        assert session.purpose == "Build feature"
        assert session.ended_at is None
        assert session.task_count == 0
        assert session.tasks_completed == 0

    def test_task_count_properties(self) -> None:
        session = OperatorSession(
            tasks=[
                TaskEntry(status="done"),
                TaskEntry(status="done"),
                TaskEntry(status="in_progress"),
                TaskEntry(status="pending"),
            ]
        )
        assert session.task_count == 4
        assert session.tasks_completed == 2

    def test_to_dict_roundtrip(self) -> None:
        now = datetime.now(UTC)
        session = OperatorSession(
            session_id="sess1",
            purpose="Test purpose",
            status=OperatorSessionStatus.COMPLETED,
            started_at=now,
            updated_at=now,
            ended_at=now,
            tenant_id="t1",
            tasks=[TaskEntry(task_id="t1", description="Task 1", status="done")],
            task_summary="1/1 done",
            context={"key": "value"},
            parent_session_id="parent1",
            cache={"tool_count": 5},
            event_count=10,
            last_checkpoint_at=now,
        )
        d = session.to_dict()
        assert d["session_id"] == "sess1"
        assert d["status"] == "completed"
        assert d["tenant_id"] == "t1"
        assert len(d["tasks"]) == 1
        assert d["parent_session_id"] == "parent1"

        restored = OperatorSession.from_dict(d)
        assert restored.session_id == "sess1"
        assert restored.status == OperatorSessionStatus.COMPLETED
        assert restored.tenant_id == "t1"
        assert len(restored.tasks) == 1
        assert restored.tasks[0].task_id == "t1"
        assert restored.parent_session_id == "parent1"
        assert restored.event_count == 10
        assert restored.last_checkpoint_at is not None

    def test_from_dict_with_minimal_data(self) -> None:
        with pytest.raises(ValueError, match="Missing started_at"):
            OperatorSession.from_dict({"session_id": "s2"})

    def test_from_dict_invalid_started_at_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Invalid started_at"):
            OperatorSession.from_dict({"session_id": "s2", "started_at": "bad"})

    def test_from_dict_missing_updated_at_raises_value_error(self) -> None:
        now = datetime.now(UTC).isoformat()
        with pytest.raises(ValueError, match="Missing updated_at"):
            OperatorSession.from_dict({"session_id": "s2", "started_at": now})

    def test_status_enum_values(self) -> None:
        assert OperatorSessionStatus.ACTIVE.value == "active"
        assert OperatorSessionStatus.COMPLETED.value == "completed"
        assert OperatorSessionStatus.CRASHED.value == "crashed"
        assert OperatorSessionStatus.SUSPENDED.value == "suspended"
