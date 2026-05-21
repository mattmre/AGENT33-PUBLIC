"""SQLite-backed persistence for outcome events (P72)."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from threading import RLock
from typing import TYPE_CHECKING

import structlog

from agent33.outcomes.models import OutcomeEvent, OutcomeMetricType

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

logger = structlog.get_logger()

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS outcome_events (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    event_type TEXT NOT NULL,
    metric_type TEXT NOT NULL,
    value REAL NOT NULL,
    occurred_at TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_tenant_occurred
    ON outcome_events(tenant_id, occurred_at);
"""


class OutcomePersistence:
    """SQLite-backed persistence for outcome events."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._lock = RLock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        """Create outcomes table if not exists."""
        with self._lock:
            self._conn.executescript(_SCHEMA_SQL)
            self._conn.commit()

    def save_event(self, event: OutcomeEvent) -> None:
        """Persist a single outcome event (best-effort).

        If the underlying connection is already closed (e.g. after lifespan
        teardown), the error is logged and silently swallowed so that
        in-memory operation continues unaffected.
        """
        try:
            with self._lock:
                self._conn.execute(
                    """INSERT OR REPLACE INTO outcome_events
                       (
                           id,
                           tenant_id,
                           domain,
                           event_type,
                           metric_type,
                           value,
                           occurred_at,
                           metadata
                       )
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event.id,
                        event.tenant_id,
                        event.domain,
                        event.event_type,
                        event.metric_type.value,
                        event.value,
                        event.occurred_at.isoformat(),
                        json.dumps(event.metadata),
                    ),
                )
                self._conn.commit()
        except sqlite3.ProgrammingError:
            logger.debug(
                "outcome_persistence_save_skipped",
                reason="connection_closed",
                event_id=event.id,
            )

    def load_events(
        self,
        *,
        tenant_id: str,
        since: datetime | None = None,
        until: datetime | None = None,
        domain: str | None = None,
        metric_types: Sequence[OutcomeMetricType] | None = None,
        limit: int | None = 1000,
    ) -> list[OutcomeEvent]:
        """Load events from SQLite, optionally filtered by tenant and date.

        Returns an empty list if the connection is already closed.
        """
        if metric_types is not None and len(metric_types) == 0:
            return []
        try:
            query = [
                """SELECT id, tenant_id, domain, event_type, metric_type,
                          value, occurred_at, metadata
                   FROM outcome_events
                   WHERE tenant_id = ?"""
            ]
            params: list[object] = [tenant_id]
            if since is not None:
                query.append("AND occurred_at >= ?")
                params.append(since.isoformat())
            if until is not None:
                query.append("AND occurred_at <= ?")
                params.append(until.isoformat())
            if domain is not None:
                query.append("AND domain = ?")
                params.append(domain)
            if metric_types is not None:
                placeholders = ", ".join("?" for _ in metric_types)
                query.append(f"AND metric_type IN ({placeholders})")
                params.extend(metric.value for metric in metric_types)
            query.append("ORDER BY occurred_at DESC")
            if limit is not None:
                query.append("LIMIT ?")
                params.append(limit)
            with self._lock:
                cursor = self._conn.execute(" ".join(query), params)
                rows = cursor.fetchall()
            return [self._row_to_event(row) for row in rows]
        except sqlite3.ProgrammingError:
            logger.debug(
                "outcome_persistence_load_skipped",
                reason="connection_closed",
                tenant_id=tenant_id,
            )
            return []

    def load_most_recent_event(self) -> OutcomeEvent | None:
        """Return the most recent persisted event across all tenants, if any."""
        try:
            with self._lock:
                cursor = self._conn.execute(
                    """SELECT id, tenant_id, domain, event_type, metric_type,
                              value, occurred_at, metadata
                       FROM outcome_events
                       ORDER BY occurred_at DESC
                       LIMIT 1"""
                )
                row = cursor.fetchone()
        except sqlite3.ProgrammingError:
            logger.debug(
                "outcome_persistence_latest_skipped",
                reason="connection_closed",
            )
            return None
        return self._row_to_event(row) if row is not None else None

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> OutcomeEvent:
        """Convert a database row to an OutcomeEvent."""
        occurred_at_str: str = row["occurred_at"]
        # Handle both timezone-aware and naive ISO formats
        if occurred_at_str.endswith("+00:00") or occurred_at_str.endswith("Z"):
            occurred_at = datetime.fromisoformat(occurred_at_str.replace("Z", "+00:00"))
        else:
            occurred_at = datetime.fromisoformat(occurred_at_str).replace(tzinfo=UTC)
        return OutcomeEvent(
            id=row["id"],
            tenant_id=row["tenant_id"],
            domain=row["domain"],
            event_type=row["event_type"],
            metric_type=OutcomeMetricType(row["metric_type"]),
            value=row["value"],
            occurred_at=occurred_at,
            metadata=json.loads(row["metadata"]),
        )

    def close(self) -> None:
        """Close the SQLite connection."""
        try:
            with self._lock:
                self._conn.close()
        except Exception:
            logger.warning("outcome_persistence_close_error", exc_info=True)
