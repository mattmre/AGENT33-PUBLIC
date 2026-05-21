"""Session trajectory tracking (Phase 59).

Tracks the arc of a session: milestones, duration, token usage over time,
and outcome.  Integrates with the observation capture pipeline to record
events as they happen, producing a lightweight metadata-only trajectory
for each session.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums and models
# ---------------------------------------------------------------------------


class SessionOutcome(StrEnum):
    """Final outcome of a session."""

    PENDING = "pending"
    SUCCESS = "success"
    FAILURE = "failure"
    ABANDONED = "abandoned"


class TrajectoryEventKind(StrEnum):
    """Kind of event recorded on a trajectory."""

    SESSION_START = "session_start"
    USER_MESSAGE = "user_message"
    AGENT_RESPONSE = "agent_response"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ERROR = "error"
    MILESTONE = "milestone"
    TITLE_SET = "title_set"
    SESSION_END = "session_end"


class TrajectoryEvent(BaseModel):
    """A single lightweight event in a session trajectory.

    Contains only metadata -- no full message content, keeping the
    trajectory compact.
    """

    kind: TrajectoryEventKind
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    agent_name: str = ""
    detail: str = ""
    token_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class TokenUsagePoint(BaseModel):
    """A point-in-time token usage measurement."""

    timestamp: datetime
    cumulative_tokens: int


class SessionTrajectory(BaseModel):
    """The full trajectory of a session.

    Tracks the session arc from start to end, including milestones,
    token usage over time, and final outcome.
    """

    session_id: str
    title: str = ""
    start_time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    end_time: datetime | None = None
    duration_seconds: float = 0.0
    outcome: SessionOutcome = SessionOutcome.PENDING
    events: list[TrajectoryEvent] = Field(default_factory=list)
    token_usage: list[TokenUsagePoint] = Field(default_factory=list)
    total_tokens: int = 0
    total_user_messages: int = 0
    total_agent_responses: int = 0
    total_tool_calls: int = 0
    total_errors: int = 0
    first_user_message: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def event_count(self) -> int:
        """Total number of recorded events."""
        return len(self.events)


# Rebuild so PEP 563 deferred annotations resolve at runtime.
TrajectoryEvent.model_rebuild()
TokenUsagePoint.model_rebuild()
SessionTrajectory.model_rebuild()


# ---------------------------------------------------------------------------
# Trajectory tracker service
# ---------------------------------------------------------------------------


class SessionTrajectoryTracker:
    """In-memory tracker for session trajectories.

    Records events against session IDs and maintains running counters.
    Designed to be wired into the observation capture pipeline.
    """

    def __init__(self) -> None:
        self._trajectories: dict[str, SessionTrajectory] = {}

    # -- lifecycle ----------------------------------------------------------

    def start_session(
        self,
        session_id: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> SessionTrajectory:
        """Begin tracking a new session trajectory.

        If the session already exists, returns the existing trajectory
        (idempotent for retries/reconnects).
        """
        if session_id in self._trajectories:
            return self._trajectories[session_id]

        now = datetime.now(UTC)
        trajectory = SessionTrajectory(
            session_id=session_id,
            start_time=now,
            metadata=metadata or {},
        )
        trajectory.events.append(
            TrajectoryEvent(
                kind=TrajectoryEventKind.SESSION_START,
                timestamp=now,
            )
        )
        self._trajectories[session_id] = trajectory
        logger.debug("trajectory_started session_id=%s", session_id)
        return trajectory

    def end_session(
        self,
        session_id: str,
        outcome: SessionOutcome = SessionOutcome.SUCCESS,
    ) -> SessionTrajectory:
        """Mark a session trajectory as ended.

        Raises:
            KeyError: If the session is not being tracked.
        """
        trajectory = self.get(session_id)
        now = datetime.now(UTC)
        trajectory.end_time = now
        trajectory.outcome = outcome
        trajectory.duration_seconds = (now - trajectory.start_time).total_seconds()
        trajectory.events.append(
            TrajectoryEvent(
                kind=TrajectoryEventKind.SESSION_END,
                timestamp=now,
                detail=outcome.value,
            )
        )
        logger.debug(
            "trajectory_ended session_id=%s outcome=%s duration=%.1fs",
            session_id,
            outcome.value,
            trajectory.duration_seconds,
        )
        return trajectory

    # -- event recording ----------------------------------------------------

    def record_event(
        self,
        session_id: str,
        kind: TrajectoryEventKind,
        *,
        agent_name: str = "",
        detail: str = "",
        token_count: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> TrajectoryEvent:
        """Record a trajectory event for the given session.

        If the session is not yet tracked, a new trajectory is created
        automatically (supports late-start recording).

        Returns the created event.
        """
        if session_id not in self._trajectories:
            self.start_session(session_id)

        trajectory = self._trajectories[session_id]

        event = TrajectoryEvent(
            kind=kind,
            agent_name=agent_name,
            detail=detail,
            token_count=token_count,
            metadata=metadata or {},
        )
        trajectory.events.append(event)

        # Update running counters.
        trajectory.total_tokens += token_count
        if token_count > 0:
            trajectory.token_usage.append(
                TokenUsagePoint(
                    timestamp=event.timestamp,
                    cumulative_tokens=trajectory.total_tokens,
                )
            )

        if kind == TrajectoryEventKind.USER_MESSAGE:
            trajectory.total_user_messages += 1
            # Capture the first user message for title generation.
            if trajectory.total_user_messages == 1 and detail:
                trajectory.first_user_message = detail
        elif kind == TrajectoryEventKind.AGENT_RESPONSE:
            trajectory.total_agent_responses += 1
        elif kind == TrajectoryEventKind.TOOL_CALL:
            trajectory.total_tool_calls += 1
        elif kind == TrajectoryEventKind.ERROR:
            trajectory.total_errors += 1

        return event

    def set_title(self, session_id: str, title: str) -> None:
        """Set or update the title on a session trajectory.

        Raises:
            KeyError: If the session is not being tracked.
        """
        trajectory = self.get(session_id)
        trajectory.title = title
        trajectory.events.append(
            TrajectoryEvent(
                kind=TrajectoryEventKind.TITLE_SET,
                detail=title,
            )
        )

    # -- retrieval ----------------------------------------------------------

    def get(self, session_id: str) -> SessionTrajectory:
        """Retrieve the trajectory for a session.

        Raises:
            KeyError: If the session is not being tracked.
        """
        trajectory = self._trajectories.get(session_id)
        if trajectory is None:
            raise KeyError(f"Session '{session_id}' not found in trajectory tracker")
        # Update duration for active sessions.
        if trajectory.end_time is None:
            trajectory.duration_seconds = (
                datetime.now(UTC) - trajectory.start_time
            ).total_seconds()
        return trajectory

    def list_sessions(self) -> list[str]:
        """Return all tracked session IDs."""
        return list(self._trajectories.keys())

    def remove(self, session_id: str) -> None:
        """Remove a session trajectory from the tracker.

        No-op if the session is not tracked.
        """
        self._trajectories.pop(session_id, None)

    @property
    def session_count(self) -> int:
        """Number of sessions currently tracked."""
        return len(self._trajectories)
