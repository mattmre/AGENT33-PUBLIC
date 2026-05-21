"""Filesystem-backed storage for operator sessions and replay logs."""

from __future__ import annotations

import json
import logging
import os
import platform
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from agent33.sessions.models import (
    OperatorSession,
    OperatorSessionStatus,
    SessionEvent,
)

logger = logging.getLogger(__name__)

_SAFE_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class FileSessionStorage:
    """Filesystem storage backend for operator sessions.

    Layout under base_dir:
        <session_id>/
            session.json        -- serialized OperatorSession
            replay.jsonl        -- append-only event log
            checkpoint.json     -- latest checkpoint snapshot
            process.lock        -- PID-based lock file
    """

    def __init__(
        self,
        base_dir: Path,
        max_replay_file_bytes: int = 50 * 1024 * 1024,
    ) -> None:
        self._base_dir = base_dir
        self._max_replay_bytes = max_replay_file_bytes

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    def ensure_base_dir(self) -> None:
        """Create the base sessions directory if it does not exist."""
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def session_dir(self, session_id: str) -> Path:
        """Return the directory for a specific session."""
        return self._base_dir / self._validate_session_id(session_id)

    # ------------------------------------------------------------------
    # Session CRUD
    # ------------------------------------------------------------------

    def save_session(self, session: OperatorSession) -> None:
        """Write session state to session.json."""
        sdir = self.session_dir(session.session_id)
        sdir.mkdir(parents=True, exist_ok=True)
        session_file = sdir / "session.json"
        session_file.write_text(
            json.dumps(session.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

    def load_session(self, session_id: str) -> OperatorSession | None:
        """Load a session from session.json. Returns None if not found."""
        session_file = self.session_dir(session_id) / "session.json"
        if not session_file.exists():
            return None
        try:
            raw = json.loads(session_file.read_text(encoding="utf-8"))
            return OperatorSession.from_dict(raw)
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning(
                "corrupt session file session_id=%s error=%s",
                session_id,
                exc,
            )
            return None

    def delete_session(self, session_id: str) -> bool:
        """Remove a session directory entirely. Returns True if removed."""
        import shutil

        sdir = self.session_dir(session_id)
        if sdir.exists():
            shutil.rmtree(sdir, ignore_errors=True)
            return True
        return False

    def list_session_ids(self) -> list[str]:
        """Return all session IDs on disk (directory names)."""
        if not self._base_dir.exists():
            return []
        session_ids: list[str] = []
        for directory in sorted(self._base_dir.iterdir(), key=lambda p: p.stat().st_mtime):
            if not directory.is_dir() or not (directory / "session.json").exists():
                continue
            try:
                session_ids.append(self._validate_session_id(directory.name))
            except ValueError:
                logger.warning("unsafe_session_id_skipped session_id=%s", directory.name)
        return session_ids

    def list_sessions(
        self,
        status: OperatorSessionStatus | None = None,
        limit: int = 50,
        tenant_id: str | None = None,
    ) -> list[OperatorSession]:
        """Load and return sessions with optional status filter."""
        sessions: list[OperatorSession] = []
        for sid in reversed(self.list_session_ids()):
            s = self.load_session(sid)
            if s is None:
                continue
            if tenant_id is not None and s.tenant_id != tenant_id:
                continue
            if status is not None and s.status != status:
                continue
            sessions.append(s)
            if len(sessions) >= limit:
                break
        return sessions

    @staticmethod
    def _validate_session_id(session_id: str) -> str:
        """Reject session identifiers that could escape the storage root."""
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("Invalid session ID")
        if session_id.strip() != session_id:
            raise ValueError("Invalid session ID")
        separators = {"/", "\\"}
        if os.sep:
            separators.add(os.sep)
        if os.altsep:
            separators.add(os.altsep)
        if any(separator in session_id for separator in separators):
            raise ValueError("Invalid session ID")
        if ".." in session_id or not _SAFE_SESSION_ID_RE.fullmatch(session_id):
            raise ValueError("Invalid session ID")
        return session_id

    # ------------------------------------------------------------------
    # Replay log
    # ------------------------------------------------------------------

    def append_event(self, session_id: str, event: SessionEvent) -> None:
        """Append a single event to replay.jsonl."""
        sdir = self.session_dir(session_id)
        sdir.mkdir(parents=True, exist_ok=True)
        replay_file = sdir / "replay.jsonl"
        line = json.dumps(event.to_dict(), default=str) + "\n"
        with open(replay_file, "a", encoding="utf-8") as f:
            f.write(line)

    def read_events(
        self,
        session_id: str,
        offset: int = 0,
        limit: int = 100,
    ) -> list[SessionEvent]:
        """Read events from replay.jsonl with pagination."""
        replay_file = self.session_dir(session_id) / "replay.jsonl"
        if not replay_file.exists():
            return []
        events: list[SessionEvent] = []
        with open(replay_file, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i < offset:
                    continue
                if len(events) >= limit:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(SessionEvent.from_dict(json.loads(line)))
                except (json.JSONDecodeError, KeyError, ValueError) as exc:
                    logger.warning(
                        "corrupt replay line session=%s line=%d error=%s",
                        session_id,
                        i,
                        exc,
                    )
        return events

    def event_count(self, session_id: str) -> int:
        """Count total events in replay log."""
        replay_file = self.session_dir(session_id) / "replay.jsonl"
        if not replay_file.exists():
            return 0
        count = 0
        with open(replay_file, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count

    def rotate_replay_log(self, session_id: str) -> bool:
        """Rotate replay.jsonl if it exceeds the size limit.

        Returns True if rotation occurred.
        """
        replay_file = self.session_dir(session_id) / "replay.jsonl"
        if not replay_file.exists():
            return False
        if replay_file.stat().st_size < self._max_replay_bytes:
            return False
        # Rotate by renaming with timestamp suffix
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        archived = replay_file.with_name(f"replay.{ts}.jsonl")
        replay_file.rename(archived)
        logger.info(
            "replay_log_rotated session=%s archived=%s",
            session_id,
            archived.name,
        )
        return True

    # ------------------------------------------------------------------
    # Checkpoint
    # ------------------------------------------------------------------

    def save_checkpoint(self, session: OperatorSession) -> None:
        """Write a checkpoint snapshot."""
        sdir = self.session_dir(session.session_id)
        sdir.mkdir(parents=True, exist_ok=True)
        cp_file = sdir / "checkpoint.json"
        cp_file.write_text(
            json.dumps(session.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Process lock
    # ------------------------------------------------------------------

    def write_lock(self, session_id: str) -> None:
        """Write a PID-based process lock file."""
        sdir = self.session_dir(session_id)
        sdir.mkdir(parents=True, exist_ok=True)
        lock_file = sdir / "process.lock"
        lock_data = {
            "pid": os.getpid(),
            "started_at": datetime.now(UTC).isoformat(),
            "hostname": platform.node(),
        }
        lock_file.write_text(json.dumps(lock_data), encoding="utf-8")

    def remove_lock(self, session_id: str) -> None:
        """Remove the process lock file."""
        lock_file = self.session_dir(session_id) / "process.lock"
        if lock_file.exists():
            lock_file.unlink(missing_ok=True)

    def read_lock(self, session_id: str) -> dict[str, Any] | None:
        """Read the process lock file. Returns None if absent/corrupt."""
        lock_file = self.session_dir(session_id) / "process.lock"
        if not lock_file.exists():
            return None
        try:
            return json.loads(lock_file.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
        except (json.JSONDecodeError, OSError):
            return None

    def is_process_alive(self, session_id: str) -> bool:
        """Check whether the process holding the lock is still running."""
        lock_data = self.read_lock(session_id)
        if lock_data is None:
            return False
        pid = lock_data.get("pid")
        if pid is None:
            return False
        return _pid_is_alive(int(pid))

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup_old_sessions(self, max_retained: int) -> int:
        """Remove oldest sessions when count exceeds max_retained.

        Returns the number of sessions removed.
        """
        ids = self.list_session_ids()
        if len(ids) <= max_retained:
            return 0
        to_remove = ids[: len(ids) - max_retained]
        removed = 0
        for sid in to_remove:
            if self.delete_session(sid):
                removed += 1
        logger.info("sessions_cleaned up removed=%d retained=%d", removed, max_retained)
        return removed


def _pid_is_alive(pid: int) -> bool:
    """Check whether a process with the given PID is running."""
    if platform.system() == "Windows":
        try:
            import ctypes

            windll = getattr(ctypes, "windll", None)
            if windll is None:
                return False
            kernel32 = windll.kernel32
            process_query_limited = 0x1000
            handle = kernel32.OpenProcess(process_query_limited, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
