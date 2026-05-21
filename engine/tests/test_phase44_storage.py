"""Tests for Phase 44 FileSessionStorage: filesystem persistence and replay."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from agent33.sessions.models import (
    OperatorSession,
    OperatorSessionStatus,
    SessionEvent,
    SessionEventType,
)
from agent33.sessions.storage import FileSessionStorage


class TestFileSessionStorage:
    """Tests for FileSessionStorage CRUD operations."""

    @pytest.mark.parametrize(
        "unsafe_id",
        ["../escape", "..\\escape", "nested/child", "nested\\child", ""],
    )
    def test_session_dir_rejects_unsafe_ids(self, tmp_path: Path, unsafe_id: str) -> None:
        storage = FileSessionStorage(base_dir=tmp_path)
        with pytest.raises(ValueError, match="Invalid session ID"):
            storage.session_dir(unsafe_id)

    def test_save_and_load_session(self, tmp_path: Path) -> None:
        storage = FileSessionStorage(base_dir=tmp_path)
        session = OperatorSession(
            session_id="test123",
            purpose="Test session",
            tenant_id="t1",
        )
        storage.save_session(session)

        loaded = storage.load_session("test123")
        assert loaded is not None
        assert loaded.session_id == "test123"
        assert loaded.purpose == "Test session"
        assert loaded.tenant_id == "t1"
        assert loaded.status == OperatorSessionStatus.ACTIVE

    def test_load_nonexistent_returns_none(self, tmp_path: Path) -> None:
        storage = FileSessionStorage(base_dir=tmp_path)
        assert storage.load_session("nonexistent") is None

    def test_load_corrupt_json_returns_none(self, tmp_path: Path) -> None:
        storage = FileSessionStorage(base_dir=tmp_path)
        sdir = tmp_path / "corrupt"
        sdir.mkdir()
        (sdir / "session.json").write_text("{invalid json", encoding="utf-8")
        assert storage.load_session("corrupt") is None

    def test_delete_session(self, tmp_path: Path) -> None:
        storage = FileSessionStorage(base_dir=tmp_path)
        session = OperatorSession(session_id="del1")
        storage.save_session(session)
        assert storage.load_session("del1") is not None
        assert storage.delete_session("del1") is True
        assert storage.load_session("del1") is None

    def test_delete_nonexistent_returns_false(self, tmp_path: Path) -> None:
        storage = FileSessionStorage(base_dir=tmp_path)
        assert storage.delete_session("nope") is False

    def test_list_session_ids_empty(self, tmp_path: Path) -> None:
        storage = FileSessionStorage(base_dir=tmp_path)
        assert storage.list_session_ids() == []

    def test_list_session_ids_returns_valid_sessions(self, tmp_path: Path) -> None:
        storage = FileSessionStorage(base_dir=tmp_path)
        for sid in ["a1", "b2", "c3"]:
            storage.save_session(OperatorSession(session_id=sid))
        ids = storage.list_session_ids()
        assert set(ids) == {"a1", "b2", "c3"}

    def test_list_sessions_with_status_filter(self, tmp_path: Path) -> None:
        storage = FileSessionStorage(base_dir=tmp_path)
        storage.save_session(OperatorSession(session_id="s1", status=OperatorSessionStatus.ACTIVE))
        storage.save_session(
            OperatorSession(session_id="s2", status=OperatorSessionStatus.COMPLETED)
        )
        storage.save_session(OperatorSession(session_id="s3", status=OperatorSessionStatus.ACTIVE))

        active = storage.list_sessions(status=OperatorSessionStatus.ACTIVE)
        assert len(active) == 2
        assert all(s.status == OperatorSessionStatus.ACTIVE for s in active)

        completed = storage.list_sessions(status=OperatorSessionStatus.COMPLETED)
        assert len(completed) == 1
        assert completed[0].session_id == "s2"

    def test_list_sessions_respects_limit(self, tmp_path: Path) -> None:
        storage = FileSessionStorage(base_dir=tmp_path)
        for i in range(10):
            storage.save_session(OperatorSession(session_id=f"s{i:02d}"))
        sessions = storage.list_sessions(limit=3)
        assert len(sessions) == 3


class TestFileSessionStorageReplay:
    """Tests for replay log append and read operations."""

    def test_append_and_read_events(self, tmp_path: Path) -> None:
        storage = FileSessionStorage(base_dir=tmp_path)
        sid = "replay1"

        for i in range(5):
            event = SessionEvent(
                event_id=f"e{i}",
                event_type=SessionEventType.TOOL_EXECUTED,
                session_id=sid,
                data={"index": i},
            )
            storage.append_event(sid, event)

        events = storage.read_events(sid)
        assert len(events) == 5
        assert events[0].event_id == "e0"
        assert events[4].data["index"] == 4

    def test_read_events_with_pagination(self, tmp_path: Path) -> None:
        storage = FileSessionStorage(base_dir=tmp_path)
        sid = "paged"
        for i in range(20):
            storage.append_event(
                sid,
                SessionEvent(
                    event_id=f"e{i}",
                    event_type=SessionEventType.AGENT_INVOKED,
                    session_id=sid,
                ),
            )

        page1 = storage.read_events(sid, offset=0, limit=5)
        assert len(page1) == 5
        assert page1[0].event_id == "e0"

        page2 = storage.read_events(sid, offset=5, limit=5)
        assert len(page2) == 5
        assert page2[0].event_id == "e5"

        page_end = storage.read_events(sid, offset=18, limit=10)
        assert len(page_end) == 2

    def test_read_events_empty_log(self, tmp_path: Path) -> None:
        storage = FileSessionStorage(base_dir=tmp_path)
        assert storage.read_events("no_such_session") == []

    def test_event_count(self, tmp_path: Path) -> None:
        storage = FileSessionStorage(base_dir=tmp_path)
        sid = "counted"
        assert storage.event_count(sid) == 0
        for _i in range(7):
            storage.append_event(
                sid,
                SessionEvent(
                    event_type=SessionEventType.CHECKPOINT,
                    session_id=sid,
                ),
            )
        assert storage.event_count(sid) == 7

    def test_rotate_replay_log(self, tmp_path: Path) -> None:
        storage = FileSessionStorage(base_dir=tmp_path, max_replay_file_bytes=100)
        sid = "rotated"
        # Write enough data to exceed 100 bytes
        for _i in range(20):
            storage.append_event(
                sid,
                SessionEvent(
                    event_type=SessionEventType.TOOL_EXECUTED,
                    session_id=sid,
                    data={"payload": "x" * 50},
                ),
            )
        rotated = storage.rotate_replay_log(sid)
        assert rotated is True
        # After rotation, current replay.jsonl should be gone (rotated)
        sdir = tmp_path / sid
        archived = [
            f for f in sdir.iterdir() if f.name.startswith("replay.") and f.name != "replay.jsonl"
        ]
        assert len(archived) == 1

    def test_rotate_noop_when_under_limit(self, tmp_path: Path) -> None:
        storage = FileSessionStorage(base_dir=tmp_path, max_replay_file_bytes=10 * 1024 * 1024)
        sid = "small"
        storage.append_event(
            sid,
            SessionEvent(
                event_type=SessionEventType.SESSION_STARTED,
                session_id=sid,
            ),
        )
        assert storage.rotate_replay_log(sid) is False


class TestFileSessionStorageLock:
    """Tests for process lock file operations."""

    def test_write_and_read_lock(self, tmp_path: Path) -> None:
        storage = FileSessionStorage(base_dir=tmp_path)
        storage.save_session(OperatorSession(session_id="locked"))
        storage.write_lock("locked")

        lock = storage.read_lock("locked")
        assert lock is not None
        assert "pid" in lock
        assert "hostname" in lock

    def test_read_lock_missing(self, tmp_path: Path) -> None:
        storage = FileSessionStorage(base_dir=tmp_path)
        assert storage.read_lock("nope") is None

    def test_remove_lock(self, tmp_path: Path) -> None:
        storage = FileSessionStorage(base_dir=tmp_path)
        storage.save_session(OperatorSession(session_id="rmlock"))
        storage.write_lock("rmlock")
        assert storage.read_lock("rmlock") is not None
        storage.remove_lock("rmlock")
        assert storage.read_lock("rmlock") is None

    def test_is_process_alive_for_current_process(self, tmp_path: Path) -> None:
        storage = FileSessionStorage(base_dir=tmp_path)
        storage.save_session(OperatorSession(session_id="alive"))
        storage.write_lock("alive")
        # Current process should be alive
        assert storage.is_process_alive("alive") is True

    def test_is_process_alive_for_dead_pid(self, tmp_path: Path) -> None:
        storage = FileSessionStorage(base_dir=tmp_path)
        sdir = tmp_path / "dead"
        sdir.mkdir(parents=True)
        # Write a lock with a PID that almost certainly doesn't exist
        lock_data = {"pid": 999999999, "started_at": "2026-01-01T00:00:00", "hostname": "test"}
        (sdir / "process.lock").write_text(json.dumps(lock_data), encoding="utf-8")
        assert storage.is_process_alive("dead") is False


class TestFileSessionStorageCleanup:
    """Tests for session cleanup and retention."""

    def test_cleanup_removes_oldest_sessions(self, tmp_path: Path) -> None:
        storage = FileSessionStorage(base_dir=tmp_path)
        # Create 5 sessions
        for i in range(5):
            storage.save_session(OperatorSession(session_id=f"s{i:02d}"))
        # Cleanup with max_retained=3 should remove 2
        removed = storage.cleanup_old_sessions(max_retained=3)
        assert removed == 2
        remaining = storage.list_session_ids()
        assert len(remaining) == 3

    def test_cleanup_noop_when_under_limit(self, tmp_path: Path) -> None:
        storage = FileSessionStorage(base_dir=tmp_path)
        storage.save_session(OperatorSession(session_id="s1"))
        removed = storage.cleanup_old_sessions(max_retained=10)
        assert removed == 0

    def test_save_checkpoint(self, tmp_path: Path) -> None:
        storage = FileSessionStorage(base_dir=tmp_path)
        session = OperatorSession(session_id="cp1", purpose="Checkpoint test")
        storage.save_session(session)
        storage.save_checkpoint(session)
        cp_file = tmp_path / "cp1" / "checkpoint.json"
        assert cp_file.exists()
        data = json.loads(cp_file.read_text(encoding="utf-8"))
        assert data["purpose"] == "Checkpoint test"
