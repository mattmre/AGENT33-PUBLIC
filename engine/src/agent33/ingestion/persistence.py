"""SQLite-backed persistence for CandidateAsset records.

Follows the same pattern as ``engine/src/agent33/autonomy/p69b_persistence.py``:
- ``CREATE TABLE IF NOT EXISTS`` on first connection (no Alembic migration needed).
- Upsert via ``INSERT OR REPLACE``.
- ISO-8601 strings for datetime columns (nullable columns stored as NULL).
- JSON text for the ``metadata`` dict column.

CLEAN-ROOM RESTRICTION
=======================
No code in this file may originate from the EvoMap/Evolver project.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from agent33.ingestion.models import CandidateAsset, CandidateStatus, ConfidenceLevel

if TYPE_CHECKING:
    from pathlib import Path

logger = structlog.get_logger()

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS ingestion_candidates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    status TEXT NOT NULL,
    confidence TEXT NOT NULL,
    source_uri TEXT,
    tenant_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    validated_at TEXT,
    published_at TEXT,
    revoked_at TEXT,
    revocation_reason TEXT,
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_ingestion_status
    ON ingestion_candidates(status);
CREATE INDEX IF NOT EXISTS idx_ingestion_tenant
    ON ingestion_candidates(tenant_id);
"""


class IngestionPersistence:
    """SQLite-backed persistence for ``CandidateAsset`` records."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        """Create the ingestion_candidates table and indexes if not present."""
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def save(self, asset: CandidateAsset) -> None:
        """Upsert a CandidateAsset record by id (INSERT OR REPLACE).

        Best-effort: if the connection is closed, the error is logged and
        swallowed so in-memory operation continues unaffected.
        """
        try:
            self._conn.execute(
                """INSERT OR REPLACE INTO ingestion_candidates
                   (id, name, asset_type, status, confidence, source_uri,
                    tenant_id, created_at, updated_at, validated_at,
                    published_at, revoked_at, revocation_reason, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    asset.id,
                    asset.name,
                    asset.asset_type,
                    asset.status.value,
                    asset.confidence.value,
                    asset.source_uri,
                    asset.tenant_id,
                    asset.created_at.isoformat(),
                    asset.updated_at.isoformat(),
                    asset.validated_at.isoformat() if asset.validated_at else None,
                    asset.published_at.isoformat() if asset.published_at else None,
                    asset.revoked_at.isoformat() if asset.revoked_at else None,
                    asset.revocation_reason,
                    json.dumps(asset.metadata),
                ),
            )
            self._conn.commit()
        except sqlite3.ProgrammingError:
            logger.debug(
                "ingestion_persistence_save_skipped",
                reason="connection_closed",
                asset_id=asset.id,
            )

    def delete(self, asset_id: str) -> None:
        """Delete a record by id (best-effort, swallows closed-connection errors)."""
        try:
            self._conn.execute(
                "DELETE FROM ingestion_candidates WHERE id = ?",
                (asset_id,),
            )
            self._conn.commit()
        except sqlite3.ProgrammingError:
            logger.debug(
                "ingestion_persistence_delete_skipped",
                reason="connection_closed",
                asset_id=asset_id,
            )

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def load(self, asset_id: str) -> CandidateAsset | None:
        """Load a single CandidateAsset by id, or None if not found."""
        try:
            cursor = self._conn.execute(
                "SELECT * FROM ingestion_candidates WHERE id = ?",
                (asset_id,),
            )
            row = cursor.fetchone()
            return self._row_to_asset(row) if row else None
        except sqlite3.ProgrammingError:
            logger.debug(
                "ingestion_persistence_load_skipped",
                reason="connection_closed",
                asset_id=asset_id,
            )
            return None

    def load_by_status(self, status: CandidateStatus) -> list[CandidateAsset]:
        """Load all assets with the given status, ordered by created_at ascending.

        Returns an empty list if the connection is already closed.
        """
        try:
            cursor = self._conn.execute(
                """SELECT * FROM ingestion_candidates
                   WHERE status = ?
                   ORDER BY created_at ASC""",
                (status.value,),
            )
            rows = cursor.fetchall()
            return [self._row_to_asset(row) for row in rows]
        except sqlite3.ProgrammingError:
            logger.debug(
                "ingestion_persistence_load_by_status_skipped",
                reason="connection_closed",
                status=status.value,
            )
            return []

    def load_by_tenant(self, tenant_id: str) -> list[CandidateAsset]:
        """Load all assets for the given tenant, ordered by created_at ascending.

        Returns an empty list if the connection is already closed.
        """
        try:
            cursor = self._conn.execute(
                """SELECT * FROM ingestion_candidates
                   WHERE tenant_id = ?
                   ORDER BY created_at ASC""",
                (tenant_id,),
            )
            rows = cursor.fetchall()
            return [self._row_to_asset(row) for row in rows]
        except sqlite3.ProgrammingError:
            logger.debug(
                "ingestion_persistence_load_by_tenant_skipped",
                reason="connection_closed",
                tenant_id=tenant_id,
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
            logger.warning("ingestion_persistence_close_error", exc_info=True)

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
    def _opt_dt(cls, value: Any) -> datetime | None:
        """Parse an optional ISO-8601 string; return None if the column is NULL."""
        if value is None:
            return None
        return cls._parse_dt(value)

    @classmethod
    def _row_to_asset(cls, row: sqlite3.Row) -> CandidateAsset:
        """Convert a database row to a CandidateAsset."""
        return CandidateAsset(
            id=row["id"],
            name=row["name"],
            asset_type=row["asset_type"],
            status=CandidateStatus(row["status"]),
            confidence=ConfidenceLevel(row["confidence"]),
            source_uri=row["source_uri"],
            tenant_id=row["tenant_id"],
            created_at=cls._parse_dt(row["created_at"]),
            updated_at=cls._parse_dt(row["updated_at"]),
            validated_at=cls._opt_dt(row["validated_at"]),
            published_at=cls._opt_dt(row["published_at"]),
            revoked_at=cls._opt_dt(row["revoked_at"]),
            revocation_reason=row["revocation_reason"],
            metadata=json.loads(row["metadata"]),
        )
