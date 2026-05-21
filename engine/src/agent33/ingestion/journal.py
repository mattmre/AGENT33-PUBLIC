"""Append-only transition journal for the candidate asset ingestion lifecycle.

Every lifecycle state transition is written to both an in-memory list and a
SQLite table (``ingestion_journal``), giving operators a durable, ordered audit
trail of all status changes with actor attribution.

CLEAN-ROOM RESTRICTION
=======================
No code in this file may originate from the EvoMap/Evolver project.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from agent33.ingestion.models import CandidateAsset, CandidateStatus

logger = structlog.get_logger()
_CLEANUP_INTERVAL_SECONDS = 300.0

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS ingestion_journal (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id    TEXT    NOT NULL,
    tenant_id   TEXT    NOT NULL,
    from_status TEXT    NOT NULL,
    to_status   TEXT    NOT NULL,
    event_type  TEXT    NOT NULL DEFAULT 'transition',
    operator    TEXT    NOT NULL,
    reason      TEXT    NOT NULL,
    details_json TEXT   NOT NULL DEFAULT '{}',
    occurred_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_journal_asset_id
    ON ingestion_journal(asset_id);
CREATE INDEX IF NOT EXISTS idx_journal_tenant_id
    ON ingestion_journal(tenant_id, occurred_at);
"""


class TransitionJournal:
    """Append-only log of every CandidateAsset lifecycle transition.

    Entries are stored both in-memory (for fast reads without hitting SQLite)
    and persisted to the ``ingestion_journal`` table so they survive process
    restarts.
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        retention_days: int | None = None,
    ) -> None:
        path_text = str(db_path)
        if path_text != ":memory:":
            Path(path_text).parent.mkdir(parents=True, exist_ok=True)
        self._db_path = path_text
        self._retention_days = retention_days
        self._last_cleanup_at: datetime | None = None
        self._conn = sqlite3.connect(path_text, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._entries: list[dict[str, Any]] = []
        self._configure_connection(path_text)
        self._init_schema()
        self._hydrate()

    def _configure_connection(self, path_text: str) -> None:
        """Apply SQLite pragmas that reduce lock contention for persisted journals."""
        self._conn.execute("PRAGMA busy_timeout = 5000")
        if path_text != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")

    def _init_schema(self) -> None:
        self._conn.executescript(_SCHEMA_SQL)
        self._ensure_column(
            "event_type",
            (
                "ALTER TABLE ingestion_journal "
                "ADD COLUMN event_type TEXT NOT NULL DEFAULT 'transition'"
            ),
        )
        self._ensure_column(
            "details_json",
            "ALTER TABLE ingestion_journal ADD COLUMN details_json TEXT NOT NULL DEFAULT '{}'",
        )
        self._conn.commit()

    def _ensure_column(self, column_name: str, statement: str) -> None:
        cursor = self._conn.execute("PRAGMA table_info(ingestion_journal)")
        columns = {row["name"] for row in cursor.fetchall()}
        if column_name not in columns:
            self._conn.execute(statement)

    def _hydrate(self) -> None:
        """Load existing journal entries from SQLite into the in-memory list."""
        try:
            cursor = self._conn.execute("SELECT * FROM ingestion_journal ORDER BY occurred_at ASC")
            rows = cursor.fetchall()
            self._entries = [self._row_to_dict(row) for row in rows]
            logger.info("ingestion_journal_hydrated", count=len(self._entries))
        except sqlite3.ProgrammingError:
            logger.debug("ingestion_journal_hydrate_skipped", reason="connection_closed")

    def record(
        self,
        asset: CandidateAsset,
        from_status: CandidateStatus,
        *,
        operator: str,
        reason: str,
        event_type: str = "transition",
        details: dict[str, Any] | None = None,
    ) -> None:
        """Append one transition entry.

        ``asset.status`` at the time of this call is used as ``to_status``.
        The entry is written to SQLite and appended to the in-memory list.
        """
        self._cleanup_expired_if_due()
        occurred_at = datetime.now(UTC).isoformat()
        entry: dict[str, Any] = {
            "asset_id": asset.id,
            "tenant_id": asset.tenant_id,
            "from_status": from_status.value,
            "to_status": asset.status.value,
            "event_type": event_type,
            "operator": operator,
            "reason": reason,
            "details": details or {},
            "occurred_at": occurred_at,
        }
        try:
            self._conn.execute(
                """INSERT INTO ingestion_journal
                   (
                       asset_id,
                       tenant_id,
                       from_status,
                       to_status,
                       event_type,
                       operator,
                       reason,
                       details_json,
                       occurred_at
                   )
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry["asset_id"],
                    entry["tenant_id"],
                    entry["from_status"],
                    entry["to_status"],
                    entry["event_type"],
                    entry["operator"],
                    entry["reason"],
                    json.dumps(entry["details"], sort_keys=True),
                    entry["occurred_at"],
                ),
            )
            self._conn.commit()
        except sqlite3.ProgrammingError:
            logger.debug("ingestion_journal_write_skipped", reason="connection_closed")
        self._entries.append(entry)
        logger.info(
            "ingestion_journal_recorded",
            asset_id=asset.id,
            event_type=event_type,
            from_status=from_status.value,
            to_status=asset.status.value,
            operator=operator,
        )

    def record_event(
        self,
        asset: CandidateAsset,
        *,
        event_type: str,
        operator: str,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Append a non-transition event for an asset history timeline."""
        self.record(
            asset,
            asset.status,
            operator=operator,
            reason=reason,
            event_type=event_type,
            details=details,
        )

    def entries_for(self, asset_id: str) -> list[dict[str, Any]]:
        """Return all journal entries for the given asset, ascending by occurred_at."""
        self._cleanup_expired_if_due()
        return [e for e in self._entries if e["asset_id"] == asset_id]

    def entries_for_tenant(self, tenant_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return the most-recent ``limit`` entries for the given tenant, descending."""
        self._cleanup_expired_if_due()
        tenant_entries = [e for e in self._entries if e["tenant_id"] == tenant_id]
        sorted_entries = sorted(tenant_entries, key=lambda e: e["occurred_at"], reverse=True)
        return sorted_entries[:limit]

    def cleanup_expired(self, retention_days: int | None = None) -> int:
        """Delete expired journal entries and return the number removed."""
        effective_retention_days = self._resolve_retention_days(retention_days)
        if effective_retention_days is None or effective_retention_days <= 0:
            return 0

        cutoff = datetime.now(UTC) - timedelta(days=effective_retention_days)
        cutoff_str = cutoff.isoformat()
        try:
            cursor = self._conn.execute(
                "DELETE FROM ingestion_journal WHERE occurred_at < ?",
                (cutoff_str,),
            )
            self._conn.commit()
            self._last_cleanup_at = datetime.now(UTC)
        except sqlite3.ProgrammingError:
            logger.debug(
                "ingestion_journal_cleanup_skipped",
                reason="connection_closed",
                retention_days=effective_retention_days,
            )
            return 0

        deleted = max(cursor.rowcount, 0)
        if deleted:
            self._entries = [
                entry for entry in self._entries if entry["occurred_at"] >= cutoff_str
            ]
            logger.info(
                "ingestion_journal_expired_entries_cleaned",
                deleted=deleted,
                retention_days=effective_retention_days,
            )
        return deleted

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        try:
            self._conn.close()
        except Exception:
            logger.warning("ingestion_journal_close_error", exc_info=True)

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "asset_id": row["asset_id"],
            "tenant_id": row["tenant_id"],
            "from_status": row["from_status"],
            "to_status": row["to_status"],
            "event_type": row["event_type"],
            "operator": row["operator"],
            "reason": row["reason"],
            "details": json.loads(row["details_json"]),
            "occurred_at": row["occurred_at"],
        }

    def _resolve_retention_days(self, retention_days: int | None) -> int | None:
        """Return the active retention policy for this journal."""
        return retention_days if retention_days is not None else self._retention_days

    def _cleanup_expired_if_due(self) -> None:
        """Run retention cleanup at most once per cleanup interval."""
        effective_retention_days = self._resolve_retention_days(None)
        if effective_retention_days is None or effective_retention_days <= 0:
            return
        if self._last_cleanup_at is not None:
            elapsed = (datetime.now(UTC) - self._last_cleanup_at).total_seconds()
            if elapsed < _CLEANUP_INTERVAL_SECONDS:
                return
        self.cleanup_expired()
