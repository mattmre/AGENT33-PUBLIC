"""Compaction diagnostics: recording and querying compaction events (Track 8).

Tracks every compaction operation per session, providing history and
summary statistics (total tokens saved, compaction count, average ratio).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class CompactionEvent(BaseModel):
    """Record of a single compaction operation."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    session_id: str
    messages_before: int = 0
    messages_after: int = 0
    tokens_saved: int = 0
    strategy: str = ""
    trigger_reason: str = ""


CompactionEvent.model_rebuild()


class CompactionSummary(BaseModel):
    """Aggregate statistics for compaction events on a session."""

    session_id: str
    total_compactions: int = 0
    total_tokens_saved: int = 0
    total_messages_removed: int = 0
    average_ratio: float = 0.0  # avg(messages_after / messages_before)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class CompactionDiagnostics:
    """Records compaction events and provides per-session history and summary stats.

    Events are stored in memory, keyed by session_id.
    """

    def __init__(self) -> None:
        # session_id -> list of CompactionEvent (chronological order)
        self._events: dict[str, list[CompactionEvent]] = {}

    def record(self, event: CompactionEvent) -> None:
        """Record a compaction event for a session."""
        self._events.setdefault(event.session_id, []).append(event)
        logger.debug(
            "compaction_recorded session=%s strategy=%s tokens_saved=%d",
            event.session_id,
            event.strategy,
            event.tokens_saved,
        )

    def history(self, session_id: str, *, limit: int = 100) -> list[CompactionEvent]:
        """Return compaction events for a session, newest first.

        Args:
            session_id: The session to query.
            limit: Max number of events to return (default 100).

        Returns:
            List of CompactionEvent in reverse-chronological order.
        """
        events = self._events.get(session_id, [])
        # Return newest first, up to limit
        return list(reversed(events))[:limit]

    def summary(self, session_id: str) -> CompactionSummary:
        """Compute aggregate compaction statistics for a session.

        Returns a ``CompactionSummary`` with totals and averages.
        If no compactions have been recorded, all values are zero.
        """
        events = self._events.get(session_id, [])
        if not events:
            return CompactionSummary(session_id=session_id)

        total_tokens_saved = sum(e.tokens_saved for e in events)
        total_messages_removed = sum(max(0, e.messages_before - e.messages_after) for e in events)

        # Compute average ratio: messages_after / messages_before
        ratios: list[float] = []
        for e in events:
            if e.messages_before > 0:
                ratios.append(e.messages_after / e.messages_before)
        average_ratio = sum(ratios) / len(ratios) if ratios else 0.0

        return CompactionSummary(
            session_id=session_id,
            total_compactions=len(events),
            total_tokens_saved=total_tokens_saved,
            total_messages_removed=total_messages_removed,
            average_ratio=round(average_ratio, 4),
        )

    def session_ids(self) -> list[str]:
        """Return all session ids that have compaction events."""
        return sorted(self._events.keys())

    def clear(self, session_id: str) -> int:
        """Remove all compaction events for a session.

        Returns the number of events removed.
        """
        events = self._events.pop(session_id, [])
        return len(events)
