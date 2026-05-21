"""SQLite-backed job history repository.

Provides a durable, file-based implementation of :class:`JobHistoryRepository`
using the standard library ``sqlite3`` module.  Named with the ``pg_`` prefix to
reserve the filename for a future PostgreSQL implementation while providing the
SQLite stepping-stone that can run without an external database server.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from agent33.automation.cron_models import JobRunRecord


class SqliteJobHistoryRepository:
    """SQLite-backed implementation of the job history repository protocol.

    Each :class:`JobRunRecord` is stored as a row in the ``job_run_history``
    table.  Per-job retention is enforced after each insert by removing the
    oldest records that exceed ``max_records_per_job``.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file, or ``":memory:"`` for an
        ephemeral in-memory database (useful in tests).
    max_records_per_job:
        Maximum number of history records retained per job.  Oldest
        records are evicted first when the limit is exceeded.
    """

    def __init__(
        self,
        db_path: str,
        max_records_per_job: int = 100,
    ) -> None:
        self._max_records = max_records_per_job
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS job_run_history ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  run_id TEXT NOT NULL,"
            "  job_id TEXT NOT NULL,"
            "  started_at TEXT NOT NULL,"
            "  ended_at TEXT,"
            "  status TEXT NOT NULL,"
            "  error TEXT NOT NULL DEFAULT ''"
            ")"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_job_run_history_job_id ON job_run_history (job_id)"
        )
        self._conn.commit()

    # -- protocol methods -----------------------------------------------------

    def record(self, run: JobRunRecord) -> None:
        """Store a job run record, enforcing per-job retention limits."""
        self._conn.execute(
            "INSERT INTO job_run_history (run_id, job_id, started_at, ended_at, status, error) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                run.run_id,
                run.job_id,
                run.started_at.isoformat(),
                run.ended_at.isoformat() if run.ended_at is not None else None,
                run.status,
                run.error,
            ),
        )
        # Enforce per-job retention: keep only the newest max_records rows.
        self._conn.execute(
            "DELETE FROM job_run_history "
            "WHERE job_id = ? AND id NOT IN ("
            "  SELECT id FROM job_run_history WHERE job_id = ? "
            "  ORDER BY id DESC LIMIT ?"
            ")",
            (run.job_id, run.job_id, self._max_records),
        )
        self._conn.commit()

    def query(
        self,
        job_id: str,
        limit: int = 50,
        status: str | None = None,
    ) -> list[JobRunRecord]:
        """Return run records for a job, most-recent-first.

        Optionally filter by status.
        """
        if status is not None:
            rows = self._conn.execute(
                "SELECT run_id, job_id, started_at, ended_at, status, error "
                "FROM job_run_history "
                "WHERE job_id = ? AND status = ? "
                "ORDER BY id DESC LIMIT ?",
                (job_id, status, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT run_id, job_id, started_at, ended_at, status, error "
                "FROM job_run_history "
                "WHERE job_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (job_id, limit),
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def all_job_ids(self) -> list[str]:
        """Return all job IDs that have run history."""
        rows = self._conn.execute("SELECT DISTINCT job_id FROM job_run_history").fetchall()
        return [r[0] for r in rows]

    # -- deserialisation helpers ----------------------------------------------

    @staticmethod
    def _row_to_record(
        row: tuple[str, str, str, str | None, str, str],
    ) -> JobRunRecord:
        """Convert a database row tuple to a :class:`JobRunRecord`."""
        return JobRunRecord(
            run_id=row[0],
            job_id=row[1],
            started_at=datetime.fromisoformat(row[2]).replace(tzinfo=UTC),
            ended_at=(
                datetime.fromisoformat(row[3]).replace(tzinfo=UTC) if row[3] is not None else None
            ),
            status=row[4],
            error=row[5],
        )

    # -- lifecycle ------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()
