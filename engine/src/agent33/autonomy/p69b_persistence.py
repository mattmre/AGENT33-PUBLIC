"""SQLite-backed persistence for P69b PausedInvocation records.

Uses the same pattern as engine/src/agent33/outcomes/persistence.py:
- CREATE TABLE IF NOT EXISTS on first connection (no Alembic migration needed).
- Upsert via INSERT OR REPLACE.
- ISO-8601 strings for datetime columns.
- JSON text for dict columns (tool_input).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from agent33.autonomy.p69b_models import PausedInvocation, PausedInvocationStatus

if TYPE_CHECKING:
    from pathlib import Path

logger = structlog.get_logger()

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS p69b_paused_invocations (
    id TEXT PRIMARY KEY,
    invocation_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    tool_input TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    nonce TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    resolved_at TEXT,
    approved_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_p69b_invocation_status
    ON p69b_paused_invocations(invocation_id, status);
CREATE INDEX IF NOT EXISTS idx_p69b_tenant_status
    ON p69b_paused_invocations(tenant_id, status);
"""


class P69bPersistence:
    """SQLite-backed persistence for P69b PausedInvocation records."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        """Create p69b table and indexes if not present."""
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def save(self, invocation: PausedInvocation) -> None:
        """Upsert a PausedInvocation record by id (INSERT OR REPLACE).

        Best-effort: if the connection is closed, the error is logged and
        swallowed so in-memory operation continues unaffected.
        """
        try:
            self._conn.execute(
                """INSERT OR REPLACE INTO p69b_paused_invocations
                   (id, invocation_id, tenant_id, tool_name, tool_input,
                    status, nonce, created_at, expires_at, resolved_at, approved_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    invocation.id,
                    invocation.invocation_id,
                    invocation.tenant_id,
                    invocation.tool_name,
                    json.dumps(invocation.tool_input),
                    invocation.status.value,
                    invocation.nonce,
                    invocation.created_at.isoformat(),
                    invocation.expires_at.isoformat(),
                    invocation.resolved_at.isoformat() if invocation.resolved_at else None,
                    invocation.approved_by,
                ),
            )
            self._conn.commit()
        except sqlite3.ProgrammingError:
            logger.debug(
                "p69b_persistence_save_skipped",
                reason="connection_closed",
                approval_id=invocation.id,
            )

    def delete(self, approval_id: str) -> None:
        """Delete a record by id (best-effort, swallows closed-connection errors)."""
        try:
            self._conn.execute(
                "DELETE FROM p69b_paused_invocations WHERE id = ?",
                (approval_id,),
            )
            self._conn.commit()
        except sqlite3.ProgrammingError:
            logger.debug(
                "p69b_persistence_delete_skipped",
                reason="connection_closed",
                approval_id=approval_id,
            )

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def load(self, approval_id: str) -> PausedInvocation | None:
        """Load a single PausedInvocation by id, or None if not found."""
        try:
            cursor = self._conn.execute(
                "SELECT * FROM p69b_paused_invocations WHERE id = ?",
                (approval_id,),
            )
            row = cursor.fetchone()
            return self._row_to_invocation(row) if row else None
        except sqlite3.ProgrammingError:
            logger.debug(
                "p69b_persistence_load_skipped",
                reason="connection_closed",
                approval_id=approval_id,
            )
            return None

    def load_pending(self) -> list[PausedInvocation]:
        """Load all records with status=PENDING whose expires_at is in the future.

        Returns an empty list if the connection is already closed.
        """
        now_iso = datetime.now(UTC).isoformat()
        try:
            cursor = self._conn.execute(
                """SELECT * FROM p69b_paused_invocations
                   WHERE status = ? AND expires_at > ?
                   ORDER BY created_at ASC""",
                (PausedInvocationStatus.PENDING.value, now_iso),
            )
            rows = cursor.fetchall()
            return [self._row_to_invocation(row) for row in rows]
        except sqlite3.ProgrammingError:
            logger.debug(
                "p69b_persistence_load_pending_skipped",
                reason="connection_closed",
            )
            return []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the SQLite connection."""
        try:
            self._conn.close()
        except Exception:
            logger.warning("p69b_persistence_close_error", exc_info=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_dt(value: str) -> datetime:
        """Parse an ISO-8601 string, normalising both offset-aware and naive forms."""
        if value.endswith("+00:00") or value.endswith("Z"):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return datetime.fromisoformat(value).replace(tzinfo=UTC)

    @classmethod
    def _row_to_invocation(cls, row: sqlite3.Row) -> PausedInvocation:
        """Convert a database row to a PausedInvocation."""
        resolved_at: datetime | None = None
        if row["resolved_at"] is not None:
            resolved_at = cls._parse_dt(row["resolved_at"])
        return PausedInvocation(
            id=row["id"],
            invocation_id=row["invocation_id"],
            tenant_id=row["tenant_id"],
            tool_name=row["tool_name"],
            tool_input=json.loads(row["tool_input"]),
            status=PausedInvocationStatus(row["status"]),
            nonce=row["nonce"],
            created_at=cls._parse_dt(row["created_at"]),
            expires_at=cls._parse_dt(row["expires_at"]),
            resolved_at=resolved_at,
            approved_by=row["approved_by"],
        )
