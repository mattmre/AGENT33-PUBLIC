"""Operator session models: session state, events, tasks, checkpoints."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

# ---------------------------------------------------------------------------
# Session status
# ---------------------------------------------------------------------------


class OperatorSessionStatus(StrEnum):
    """Lifecycle status of an operator session."""

    ACTIVE = "active"
    COMPLETED = "completed"
    CRASHED = "crashed"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


# ---------------------------------------------------------------------------
# Event taxonomy for replay log
# ---------------------------------------------------------------------------


class SessionEventType(StrEnum):
    """Types of events recorded in the session replay log."""

    SESSION_STARTED = "session.started"
    SESSION_ENDED = "session.ended"
    SESSION_RESUMED = "session.resumed"
    TASK_ADDED = "task.added"
    TASK_UPDATED = "task.updated"
    AGENT_INVOKED = "agent.invoked"
    TOOL_EXECUTED = "tool.executed"
    HOOK_FIRED = "hook.fired"
    CHECKPOINT = "checkpoint"
    ERROR = "error"
    USER_INPUT = "user.input"


# ---------------------------------------------------------------------------
# Task entry
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class TaskEntry:
    """A tracked task within an operator session."""

    task_id: str = dataclasses.field(default_factory=lambda: uuid4().hex[:12])
    description: str = ""
    status: Literal["pending", "in_progress", "done", "blocked"] = "pending"
    created_at: datetime = dataclasses.field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    metadata: dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly dict."""
        return {
            "task_id": self.task_id,
            "description": self.description,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "completed_at": (self.completed_at.isoformat() if self.completed_at else None),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskEntry:
        """Deserialize from a JSON dict."""
        created = data.get("created_at")
        completed = data.get("completed_at")
        return cls(
            task_id=data.get("task_id", uuid4().hex[:12]),
            description=data.get("description", ""),
            status=data.get("status", "pending"),
            created_at=_parse_optional_datetime(
                created,
                field_name="created_at",
            )
            or datetime.now(UTC),
            completed_at=_parse_optional_datetime(completed, field_name="completed_at"),
            metadata=data.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# Session event (replay log entry)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class SessionEvent:
    """A single event in the session replay log."""

    event_id: str = dataclasses.field(default_factory=lambda: uuid4().hex)
    event_type: SessionEventType = SessionEventType.SESSION_STARTED
    timestamp: datetime = dataclasses.field(default_factory=lambda: datetime.now(UTC))
    session_id: str = ""
    data: dict[str, Any] = dataclasses.field(default_factory=dict)
    correlation_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-friendly dict (one line in replay.jsonl)."""
        return {
            "event_id": self.event_id,
            "event_type": (
                self.event_type.value
                if isinstance(self.event_type, StrEnum)
                else str(self.event_type)
            ),
            "timestamp": self.timestamp.isoformat(),
            "session_id": self.session_id,
            "data": self.data,
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionEvent:
        """Deserialize from a JSON dict."""
        ts = data.get("timestamp")
        return cls(
            event_id=data.get("event_id", uuid4().hex),
            event_type=SessionEventType(data["event_type"]),
            timestamp=_parse_persisted_datetime(ts, field_name="timestamp"),
            session_id=data.get("session_id", ""),
            data=data.get("data", {}),
            correlation_id=data.get("correlation_id", ""),
        )


# ---------------------------------------------------------------------------
# Operator session
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class OperatorSession:
    """Durable operator session state for CLI-level continuity."""

    session_id: str = dataclasses.field(default_factory=lambda: uuid4().hex)
    purpose: str = ""
    status: OperatorSessionStatus = OperatorSessionStatus.ACTIVE
    started_at: datetime = dataclasses.field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = dataclasses.field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    tenant_id: str = ""

    # Task tracking
    tasks: list[TaskEntry] = dataclasses.field(default_factory=list)
    task_summary: str = ""

    # Context carry-forward
    context: dict[str, Any] = dataclasses.field(default_factory=dict)
    parent_session_id: str | None = None

    # Cache for status surfaces
    cache: dict[str, Any] = dataclasses.field(default_factory=dict)

    # Replay
    event_count: int = 0
    last_checkpoint_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-friendly dict for filesystem persistence."""
        return {
            "session_id": self.session_id,
            "purpose": self.purpose,
            "status": self.status.value,
            "started_at": self.started_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "tenant_id": self.tenant_id,
            "tasks": [t.to_dict() for t in self.tasks],
            "task_summary": self.task_summary,
            "context": self.context,
            "parent_session_id": self.parent_session_id,
            "cache": self.cache,
            "event_count": self.event_count,
            "last_checkpoint_at": (
                self.last_checkpoint_at.isoformat() if self.last_checkpoint_at else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OperatorSession:
        """Deserialize from a JSON dict."""
        started = data.get("started_at")
        updated = data.get("updated_at")
        ended = data.get("ended_at")
        last_cp = data.get("last_checkpoint_at")
        tasks_raw = data.get("tasks", [])

        return cls(
            session_id=data.get("session_id", uuid4().hex),
            purpose=data.get("purpose", ""),
            status=OperatorSessionStatus(data.get("status", "active")),
            started_at=_parse_persisted_datetime(started, field_name="started_at"),
            updated_at=_parse_persisted_datetime(updated, field_name="updated_at"),
            ended_at=_parse_optional_datetime(ended, field_name="ended_at"),
            tenant_id=data.get("tenant_id", ""),
            tasks=[TaskEntry.from_dict(t) for t in tasks_raw],
            task_summary=data.get("task_summary", ""),
            context=data.get("context", {}),
            parent_session_id=data.get("parent_session_id"),
            cache=data.get("cache", {}),
            event_count=data.get("event_count", 0),
            last_checkpoint_at=_parse_optional_datetime(
                last_cp,
                field_name="last_checkpoint_at",
            ),
        )

    @property
    def tasks_completed(self) -> int:
        """Count of tasks with status 'done'."""
        return sum(1 for t in self.tasks if t.status == "done")

    @property
    def task_count(self) -> int:
        """Total number of tracked tasks."""
        return len(self.tasks)


def _parse_persisted_datetime(value: Any, *, field_name: str) -> datetime:
    """Parse persisted required datetimes without masking missing fields."""
    if value is None:
        raise ValueError(f"Missing {field_name}")
    if not isinstance(value, str):
        raise ValueError(f"Invalid {field_name}")
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid {field_name}") from exc


def _parse_optional_datetime(value: Any, *, field_name: str) -> datetime | None:
    """Parse optional datetimes while surfacing malformed persisted data."""
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError(f"Invalid {field_name}")
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid {field_name}") from exc
