"""Durable task metrics collector for the ingestion pipeline.

Tracks per-event success/failure counts and latency in SQLite so operators can
query lightweight summaries and recent history across restarts.

CLEAN-ROOM RESTRICTION
=======================
No code in this file may originate from the EvoMap/Evolver project.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()
_CLEANUP_INTERVAL_SECONDS = 300.0

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS ingestion_task_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    success INTEGER NOT NULL,
    latency_ms REAL,
    metadata_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ingestion_task_metrics_tenant
    ON ingestion_task_metrics(tenant_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_ingestion_task_metrics_event_type
    ON ingestion_task_metrics(event_type, recorded_at DESC);
"""


class TaskMetricsCollector:
    """Durably store ingestion task-metric records with optional expiry cleanup."""

    def __init__(
        self,
        db_path: str | Path = ":memory:",
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
        self._records: list[dict[str, Any]] = []
        self._configure_connection(path_text)
        self._init_schema()
        self._hydrate()

    def _configure_connection(self, path_text: str) -> None:
        """Apply SQLite pragmas that reduce lock contention for persisted metrics."""
        self._conn.execute("PRAGMA busy_timeout = 5000")
        if path_text != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")

    def _init_schema(self) -> None:
        """Create the metrics table and indexes if not present."""
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    def _hydrate(self) -> None:
        """Load existing metrics records from SQLite into memory."""
        try:
            rows = self._conn.execute(
                """SELECT event_type, tenant_id, success, latency_ms, metadata_json, recorded_at
                   FROM ingestion_task_metrics
                   ORDER BY recorded_at ASC, id ASC"""
            ).fetchall()
            self._records = [self._row_to_dict(row) for row in rows]
            logger.info("ingestion_task_metrics_hydrated", count=len(self._records))
        except sqlite3.ProgrammingError:
            logger.debug("ingestion_task_metrics_hydrate_skipped", reason="connection_closed")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(
        self,
        event_type: str,
        tenant_id: str,
        *,
        success: bool,
        latency_ms: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Append a metrics record.

        Args:
            event_type: The type of event that was processed.
            tenant_id: Tenant scope for this record.
            success: Whether the processing succeeded.
            latency_ms: Optional elapsed time in milliseconds.
            metadata: Optional arbitrary key/value context.
        """
        self._cleanup_expired_if_due()
        record: dict[str, Any] = {
            "event_type": event_type,
            "tenant_id": tenant_id,
            "success": success,
            "latency_ms": latency_ms,
            "metadata": metadata or {},
            "recorded_at": datetime.now(UTC).isoformat(),
        }
        try:
            self._conn.execute(
                """INSERT INTO ingestion_task_metrics
                   (event_type, tenant_id, success, latency_ms, metadata_json, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    record["event_type"],
                    record["tenant_id"],
                    int(success),
                    record["latency_ms"],
                    json.dumps(record["metadata"]),
                    record["recorded_at"],
                ),
            )
            self._conn.commit()
        except sqlite3.ProgrammingError:
            logger.debug(
                "ingestion_task_metrics_record_skipped",
                reason="connection_closed",
                tenant_id=tenant_id,
                event_type=event_type,
            )
        self._records.append(record)

    def summary(self, tenant_id: str | None = None) -> dict[str, Any]:
        """Return aggregate counts and average latency.

        Args:
            tenant_id: When given, restrict to records for this tenant only.

        Returns:
            ``{"total": int, "success_count": int, "failure_count": int,
            "avg_latency_ms": float | None}``
        """
        self._cleanup_expired_if_due()
        records = self._filtered_records(tenant_id)
        total = len(records)
        success_count = sum(1 for r in records if r["success"])
        failure_count = total - success_count
        latencies = [r["latency_ms"] for r in records if r["latency_ms"] is not None]
        avg_latency: float | None = sum(latencies) / len(latencies) if latencies else None
        return {
            "total": total,
            "success_count": success_count,
            "failure_count": failure_count,
            "avg_latency_ms": avg_latency,
        }

    def history(self, tenant_id: str | None = None, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return the most recent metric records, descending by recorded_at."""
        self._cleanup_expired_if_due()
        records = sorted(
            self._filtered_records(tenant_id),
            key=lambda record: record["recorded_at"],
            reverse=True,
        )
        return records[:limit]

    def reset(self, tenant_id: str | None = None) -> None:
        """Clear records.

        Args:
            tenant_id: When given, remove only records for this tenant.
                When ``None``, clears all records.
        """
        try:
            if tenant_id is None:
                self._conn.execute("DELETE FROM ingestion_task_metrics")
            else:
                self._conn.execute(
                    "DELETE FROM ingestion_task_metrics WHERE tenant_id = ?",
                    (tenant_id,),
                )
            self._conn.commit()
        except sqlite3.ProgrammingError:
            logger.debug(
                "ingestion_task_metrics_reset_skipped",
                reason="connection_closed",
                tenant_id=tenant_id,
            )

        if tenant_id is None:
            self._records.clear()
        else:
            self._records = [
                record for record in self._records if record["tenant_id"] != tenant_id
            ]

    def cleanup_expired(self, retention_days: int | None = None) -> int:
        """Delete expired records and return the number removed."""
        effective_retention_days = self._resolve_retention_days(retention_days)
        if effective_retention_days is None or effective_retention_days <= 0:
            return 0

        cutoff = datetime.now(UTC) - timedelta(days=effective_retention_days)
        cutoff_str = cutoff.isoformat()
        try:
            cursor = self._conn.execute(
                "DELETE FROM ingestion_task_metrics WHERE recorded_at < ?",
                (cutoff_str,),
            )
            self._conn.commit()
            self._last_cleanup_at = datetime.now(UTC)
        except sqlite3.ProgrammingError:
            logger.debug(
                "ingestion_task_metrics_cleanup_skipped",
                reason="connection_closed",
                retention_days=effective_retention_days,
            )
            return 0

        deleted = max(cursor.rowcount, 0)
        if deleted:
            self._records = [
                record for record in self._records if record["recorded_at"] >= cutoff_str
            ]
            logger.info(
                "ingestion_task_metrics_expired_records_cleaned",
                deleted=deleted,
                retention_days=effective_retention_days,
            )
        return deleted

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        try:
            self._conn.close()
        except Exception:
            logger.warning(
                "ingestion_task_metrics_close_error",
                db_path=self._db_path,
                exc_info=True,
            )

    def _filtered_records(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        """Return in-memory records optionally filtered by tenant."""
        if tenant_id is None:
            return list(self._records)
        return [record for record in self._records if record["tenant_id"] == tenant_id]

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        metadata_raw = json.loads(str(row["metadata_json"]))
        metadata = metadata_raw if isinstance(metadata_raw, dict) else {}
        latency_ms = float(row["latency_ms"]) if row["latency_ms"] is not None else None
        return {
            "event_type": row["event_type"],
            "tenant_id": row["tenant_id"],
            "success": bool(row["success"]),
            "latency_ms": latency_ms,
            "metadata": metadata,
            "recorded_at": row["recorded_at"],
        }

    def _resolve_retention_days(self, retention_days: int | None) -> int | None:
        """Return the active retention policy for this collector."""
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
