"""SQLite persistence backend for security scan runs and findings."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from agent33.component_security.models import SecurityFinding, SecurityRun

logger = structlog.get_logger()

_FINDING_INSERT_SQL = """
INSERT OR REPLACE INTO scan_findings
    (id, run_id, tool, file_path, line_number, severity, category,
     cwe_id, title, description, recommendation, fingerprint, created_at,
     finding_payload)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS scan_runs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT '',
    profile TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    target_path TEXT NOT NULL DEFAULT '',
    tools_used TEXT NOT NULL DEFAULT '[]',
    summary TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    run_payload TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS scan_findings (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    tool TEXT NOT NULL DEFAULT '',
    file_path TEXT NOT NULL DEFAULT '',
    line_number INTEGER,
    severity TEXT NOT NULL,
    category TEXT NOT NULL,
    cwe_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    recommendation TEXT NOT NULL DEFAULT '',
    fingerprint TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    finding_payload TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (run_id) REFERENCES scan_runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_scan_findings_run_id ON scan_findings(run_id);
CREATE INDEX IF NOT EXISTS idx_scan_runs_tenant_id ON scan_runs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_scan_runs_created_at ON scan_runs(created_at);
"""


def _dt_to_str(dt: datetime | None) -> str | None:
    """Serialize a datetime to ISO-8601 string or None."""
    if dt is None:
        return None
    return dt.isoformat()


def _str_to_dt(value: str | None) -> datetime | None:
    """Deserialize an ISO-8601 string to datetime or None."""
    if value is None:
        return None
    return datetime.fromisoformat(value)


class SecurityScanStore:
    """SQLite-backed durable store for security scan runs and findings."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        self._conn = conn
        return conn

    def _ensure_schema(self) -> None:
        conn = self._connect()
        conn.executescript(_SCHEMA_SQL)
        self._ensure_column(
            conn,
            table_name="scan_runs",
            column_name="run_payload",
            definition="TEXT NOT NULL DEFAULT '{}'",
        )
        self._ensure_column(
            conn,
            table_name="scan_findings",
            column_name="finding_payload",
            definition="TEXT NOT NULL DEFAULT '{}'",
        )
        conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Run operations
    # ------------------------------------------------------------------

    def save_run(self, run: SecurityRun) -> None:
        """Insert or update a security scan run."""
        conn = self._connect()
        summary = run.findings_summary.model_dump(mode="json")
        tools_used = run.metadata.tools_executed
        run_payload = json.dumps(run.model_dump(mode="json"))
        conn.execute(
            """
            INSERT INTO scan_runs
                (id, tenant_id, profile, status, started_at, completed_at,
                 target_path, tools_used, summary, created_at, run_payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                tenant_id = excluded.tenant_id,
                profile = excluded.profile,
                status = excluded.status,
                started_at = excluded.started_at,
                completed_at = excluded.completed_at,
                target_path = excluded.target_path,
                tools_used = excluded.tools_used,
                summary = excluded.summary,
                created_at = excluded.created_at,
                run_payload = excluded.run_payload
            """,
            (
                run.id,
                run.tenant_id,
                run.profile.value if hasattr(run.profile, "value") else run.profile,
                run.status.value if hasattr(run.status, "value") else run.status,
                _dt_to_str(run.started_at),
                _dt_to_str(run.completed_at),
                run.target.repository_path,
                json.dumps(tools_used),
                json.dumps(summary),
                _dt_to_str(run.created_at),
                run_payload,
            ),
        )
        conn.commit()
        logger.debug("security_scan_store_run_saved", run_id=run.id)

    def get_run(self, run_id: str) -> dict[str, object] | None:
        """Return a run as a raw dict or None if not found."""
        conn = self._connect()
        row = conn.execute("SELECT * FROM scan_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_run_dict(row)

    def list_runs(
        self,
        *,
        tenant_id: str | None = None,
        status: str | None = None,
        profile: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        """List runs with optional tenant filter, newest first."""
        conn = self._connect()
        where_clauses: list[str] = []
        params: list[object] = []
        if tenant_id is not None:
            where_clauses.append("tenant_id = ?")
            params.append(tenant_id)
        if status is not None:
            where_clauses.append("status = ?")
            params.append(status)
        if profile is not None:
            where_clauses.append("profile = ?")
            params.append(profile)

        query = "SELECT * FROM scan_runs"
        if where_clauses:
            query = f"{query} WHERE {' AND '.join(where_clauses)}"
        query = f"{query} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_run_dict(row) for row in rows]

    def delete_run(self, run_id: str) -> bool:
        """Delete a run and its associated findings. Returns True if deleted."""
        conn = self._connect()
        # Foreign-key cascade deletes findings automatically.
        cursor = conn.execute("DELETE FROM scan_runs WHERE id = ?", (run_id,))
        conn.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            logger.debug("security_scan_store_run_deleted", run_id=run_id)
        return deleted

    # ------------------------------------------------------------------
    # Finding operations
    # ------------------------------------------------------------------

    def save_findings(self, findings: list[SecurityFinding]) -> int:
        """Bulk-insert findings. Returns the count of rows inserted."""
        if not findings:
            return 0
        conn = self._connect()
        rows = self._finding_rows(findings)
        conn.executemany(_FINDING_INSERT_SQL, rows)
        conn.commit()
        logger.debug("security_scan_store_findings_saved", count=len(rows))
        return len(rows)

    def replace_findings(self, run_id: str, findings: list[SecurityFinding]) -> int:
        """Replace all persisted findings for one run."""
        conn = self._connect()
        rows = self._finding_rows(findings)
        with conn:
            conn.execute("DELETE FROM scan_findings WHERE run_id = ?", (run_id,))
            if rows:
                conn.executemany(_FINDING_INSERT_SQL, rows)
        logger.debug("security_scan_store_findings_replaced", run_id=run_id, count=len(rows))
        return len(rows)

    def get_findings(self, run_id: str) -> list[dict[str, object]]:
        """Return all findings for a run as raw dicts."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM scan_findings WHERE run_id = ? ORDER BY created_at",
            (run_id,),
        ).fetchall()
        return [self._row_to_finding_dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup_expired_runs(self, retention_days: int = 90) -> int:
        """Delete runs older than *retention_days*. Returns count deleted."""
        conn = self._connect()
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        cutoff_str = cutoff.isoformat()
        cursor = conn.execute(
            "DELETE FROM scan_runs WHERE created_at < ?",
            (cutoff_str,),
        )
        conn.commit()
        deleted = cursor.rowcount
        if deleted:
            logger.info(
                "security_scan_store_expired_runs_cleaned",
                deleted=deleted,
                retention_days=retention_days,
            )
        return deleted

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_run_dict(row: sqlite3.Row) -> dict[str, object]:
        return {
            "id": row["id"],
            "tenant_id": row["tenant_id"],
            "profile": row["profile"],
            "status": row["status"],
            "started_at": _str_to_dt(row["started_at"]),
            "completed_at": _str_to_dt(row["completed_at"]),
            "target_path": row["target_path"],
            "tools_used": json.loads(row["tools_used"]),
            "summary": json.loads(row["summary"]),
            "created_at": _str_to_dt(row["created_at"]),
            "payload": _load_payload(row["run_payload"]),
        }

    @staticmethod
    def _row_to_finding_dict(row: sqlite3.Row) -> dict[str, object]:
        return {
            "id": row["id"],
            "run_id": row["run_id"],
            "tool": row["tool"],
            "file_path": row["file_path"],
            "line_number": row["line_number"],
            "severity": row["severity"],
            "category": row["category"],
            "cwe_id": row["cwe_id"],
            "title": row["title"],
            "description": row["description"],
            "recommendation": row["recommendation"],
            "fingerprint": row["fingerprint"],
            "created_at": _str_to_dt(row["created_at"]),
            "payload": _load_payload(row["finding_payload"]),
        }

    @staticmethod
    def _ensure_column(
        conn: sqlite3.Connection,
        *,
        table_name: str,
        column_name: str,
        definition: str,
    ) -> None:
        existing_columns = {
            str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name in existing_columns:
            return
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")

    @staticmethod
    def _finding_rows(findings: list[SecurityFinding]) -> list[tuple[object, ...]]:
        return [
            (
                finding.id,
                finding.run_id,
                finding.tool,
                finding.file_path,
                finding.line_number,
                finding.severity.value,
                finding.category.value,
                finding.cwe_id,
                finding.title,
                finding.description,
                finding.remediation,
                getattr(finding, "fingerprint", ""),
                _dt_to_str(finding.created_at),
                json.dumps(finding.model_dump(mode="json")),
            )
            for finding in findings
        ]


def _load_payload(value: str) -> dict[str, object]:
    """Deserialize a persisted payload column with a safe fallback."""
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}
