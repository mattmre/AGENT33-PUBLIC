"""SQLite-backed persistence for queued ingestion mailbox inbox events.

Non-``candidate_asset`` mailbox events are stored durably so they survive
process restarts until an operator drains them.

CLEAN-ROOM RESTRICTION
=======================
No code in this file may originate from the EvoMap/Evolver project.
"""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from pathlib import Path

logger = structlog.get_logger()

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS ingestion_mailbox_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    received_at TEXT NOT NULL,
    event_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ingestion_mailbox_tenant
    ON ingestion_mailbox_events(tenant_id, id);
"""


class MailboxInboxPersistence:
    """SQLite-backed queue storage for mailbox inbox events."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        path_text = str(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path_text, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._configure_connection(path_text)
        self._init_schema()

    def _configure_connection(self, path_text: str) -> None:
        """Apply SQLite pragmas that reduce lock contention for persisted queues."""
        self._conn.execute("PRAGMA busy_timeout = 5000")
        if path_text != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")

    def _init_schema(self) -> None:
        """Create the mailbox queue table and indexes if not present."""
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    def enqueue(self, stamped_event: dict[str, Any]) -> None:
        """Persist one stamped mailbox event."""
        try:
            self._conn.execute(
                """INSERT INTO ingestion_mailbox_events
                   (tenant_id, event_type, received_at, event_json)
                   VALUES (?, ?, ?, ?)""",
                (
                    str(stamped_event["tenant_id"]),
                    str(stamped_event["event_type"]),
                    str(stamped_event["received_at"]),
                    json.dumps(stamped_event),
                ),
            )
            self._conn.commit()
        except sqlite3.ProgrammingError:
            logger.debug(
                "ingestion_mailbox_enqueue_skipped",
                reason="connection_closed",
                event_id=stamped_event.get("event_id"),
            )

    def drain(self, tenant_id: str) -> list[dict[str, Any]]:
        """Return and delete all queued events for ``tenant_id``, oldest first."""
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            rows = self._conn.execute(
                """SELECT id, event_json
                   FROM ingestion_mailbox_events
                   WHERE tenant_id = ?
                   ORDER BY id ASC""",
                (tenant_id,),
            ).fetchall()
            if not rows:
                self._conn.commit()
                return []

            ids = [int(row["id"]) for row in rows]
            placeholders = ", ".join("?" for _ in ids)
            self._conn.execute(
                f"DELETE FROM ingestion_mailbox_events WHERE id IN ({placeholders})",
                ids,
            )
            self._conn.commit()
            return [json.loads(str(row["event_json"])) for row in rows]
        except sqlite3.ProgrammingError:
            logger.debug(
                "ingestion_mailbox_drain_skipped",
                reason="connection_closed",
                tenant_id=tenant_id,
            )
            return []
        except Exception:
            self._conn.rollback()
            raise

    def depth(self) -> int:
        """Return the total number of queued mailbox events across all tenants."""
        try:
            row = self._conn.execute(
                "SELECT COUNT(*) AS inbox_depth FROM ingestion_mailbox_events"
            ).fetchone()
            return int(row["inbox_depth"]) if row is not None else 0
        except sqlite3.ProgrammingError:
            logger.debug("ingestion_mailbox_depth_skipped", reason="connection_closed")
            return 0

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        try:
            self._conn.close()
        except Exception:
            logger.warning(
                "ingestion_mailbox_persistence_close_error",
                db_path=str(self._db_path),
                exc_info=True,
            )
