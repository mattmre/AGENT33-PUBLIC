"""SQLite-backed persistence for explanation artifacts."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import structlog

from agent33.explanation.models import ExplanationMetadata

logger = structlog.get_logger()

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS explanations (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    fact_check_status TEXT NOT NULL,
    content TEXT NOT NULL,
    claims_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_explanations_entity_type
    ON explanations(entity_type)
"""


class ExplanationStore:
    """Persist and retrieve explanation metadata using a local SQLite database.

    The store is synchronous (sqlite3 is not async).  All route handlers that
    call it are already running in the event-loop thread, so blocking I/O on a
    small local DB is acceptable here.  For high-throughput needs the store can
    be replaced with an async backend without changing the call sites.

    When ``db_path`` is ``":memory:"`` the store keeps a single persistent
    connection so that the in-memory database is shared across all operations
    on the same instance (SQLite `:memory:` databases are per-connection).
    """

    def __init__(self, db_path: str = "data/explanations.db") -> None:
        self._db_path = db_path
        self._memory_conn: sqlite3.Connection | None = None
        self._init_db()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Return a database connection.

        For `:memory:` databases a single long-lived connection is reused so
        that DDL and data survive across method calls on the same instance.
        For file-backed databases a fresh connection is opened each time
        (sqlite3 handles concurrent access correctly at the OS level).
        """
        if self._db_path == ":memory:":
            if self._memory_conn is None:
                self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
                self._memory_conn.row_factory = sqlite3.Row
            return self._memory_conn

        path = Path(self._db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        conn.execute(_CREATE_TABLE_SQL)
        conn.execute(_CREATE_INDEX_SQL)
        conn.commit()
        logger.debug("explanation_store_initialized", db_path=self._db_path)

    @staticmethod
    def _row_to_metadata(row: sqlite3.Row) -> ExplanationMetadata:
        data: dict[str, Any] = {
            "id": row["id"],
            "entity_type": row["entity_type"],
            "entity_id": row["entity_id"],
            "mode": row["mode"],
            "fact_check_status": row["fact_check_status"],
            "content": row["content"],
            "claims": json.loads(row["claims_json"]),
            "metadata": json.loads(row["metadata_json"]),
            "created_at": row["created_at"],
        }
        return ExplanationMetadata.model_validate(data)

    @staticmethod
    def _metadata_to_row(meta: ExplanationMetadata) -> tuple[Any, ...]:
        return (
            meta.id,
            meta.entity_type,
            meta.entity_id,
            meta.mode.value,
            meta.fact_check_status.value,
            meta.content,
            json.dumps([c.model_dump(mode="json") for c in meta.claims]),
            json.dumps(meta.metadata),
            meta.created_at.isoformat(),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(self, metadata: ExplanationMetadata) -> None:
        """Insert or replace an explanation record."""
        row = self._metadata_to_row(metadata)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO explanations
                    (id, entity_type, entity_id, mode, fact_check_status,
                     content, claims_json, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )
            conn.commit()
        logger.debug("explanation_saved", explanation_id=metadata.id)

    def get(self, explanation_id: str) -> ExplanationMetadata | None:
        """Return a single explanation by ID, or None if not found."""
        with self._connect() as conn:
            cursor = conn.execute("SELECT * FROM explanations WHERE id = ?", (explanation_id,))
            row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_metadata(row)

    def list(
        self,
        entity_type: str | None = None,
        entity_id: str | None = None,
        limit: int = 50,
    ) -> list[ExplanationMetadata]:
        """Return explanations, optionally filtered, newest-first."""
        clauses: list[str] = []
        params: list[Any] = []
        if entity_type is not None:
            clauses.append("entity_type = ?")
            params.append(entity_type)
        if entity_id is not None:
            clauses.append("entity_id = ?")
            params.append(entity_id)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)

        with self._connect() as conn:
            cursor = conn.execute(
                f"SELECT * FROM explanations {where} ORDER BY created_at DESC LIMIT ?",
                params,
            )
            rows = cursor.fetchall()

        return [self._row_to_metadata(row) for row in rows]

    def delete(self, explanation_id: str) -> bool:
        """Delete an explanation by ID.  Returns True if a row was deleted."""
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM explanations WHERE id = ?", (explanation_id,))
            conn.commit()
            deleted = cursor.rowcount > 0
        if deleted:
            logger.debug("explanation_deleted", explanation_id=explanation_id)
        return deleted
