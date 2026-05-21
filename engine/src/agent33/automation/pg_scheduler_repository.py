"""SQLite-backed scheduler job repository.

Provides a durable, file-based implementation of :class:`SchedulerJobRepository`
using the standard library ``sqlite3`` module.  Named with the ``pg_`` prefix to
reserve the filename for a future PostgreSQL implementation while providing the
SQLite stepping-stone that can run without an external database server.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from agent33.automation.scheduler import ScheduledJob


class SqliteSchedulerJobRepository:
    """SQLite-backed implementation of the scheduler job repository protocol.

    Each :class:`ScheduledJob` is serialised as a JSON blob and stored in a
    single ``scheduled_jobs`` table keyed by ``job_id``.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file, or ``":memory:"`` for an
        ephemeral in-memory database (useful in tests).
    """

    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS scheduled_jobs "
            "(job_id TEXT PRIMARY KEY, data TEXT NOT NULL)"
        )
        self._conn.commit()

    # -- protocol methods -----------------------------------------------------

    def get_job(self, job_id: str) -> ScheduledJob | None:
        """Get a scheduled job by ID."""
        row = self._conn.execute(
            "SELECT data FROM scheduled_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        if row is None:
            return None
        return self._deserialize(row[0])

    def list_jobs(self) -> list[ScheduledJob]:
        """List all scheduled jobs."""
        rows = self._conn.execute("SELECT data FROM scheduled_jobs").fetchall()
        return [self._deserialize(r[0]) for r in rows]

    def add_job(self, job: ScheduledJob) -> None:
        """Store a scheduled job (insert-or-replace)."""
        self._conn.execute(
            "INSERT OR REPLACE INTO scheduled_jobs (job_id, data) VALUES (?, ?)",
            (job.job_id, self._serialize(job)),
        )
        self._conn.commit()

    def remove_job(self, job_id: str) -> bool:
        """Remove a scheduled job by ID. Returns True if found and removed."""
        cursor = self._conn.execute("DELETE FROM scheduled_jobs WHERE job_id = ?", (job_id,))
        self._conn.commit()
        return cursor.rowcount > 0

    # -- serialisation helpers ------------------------------------------------

    @staticmethod
    def _serialize(job: ScheduledJob) -> str:
        """Serialise a :class:`ScheduledJob` dataclass to a JSON string."""
        data: dict[str, Any] = {
            "job_id": job.job_id,
            "workflow_name": job.workflow_name,
            "schedule_type": job.schedule_type,
            "schedule_expr": job.schedule_expr,
            "inputs": job.inputs,
        }
        return json.dumps(data)

    @staticmethod
    def _deserialize(raw: str) -> ScheduledJob:
        """Deserialise a JSON string back to a :class:`ScheduledJob`."""
        data: dict[str, Any] = json.loads(raw)
        return ScheduledJob(
            job_id=data["job_id"],
            workflow_name=data["workflow_name"],
            schedule_type=data["schedule_type"],
            schedule_expr=data["schedule_expr"],
            inputs=data["inputs"],
        )

    # -- lifecycle ------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()
