"""SQLite-backed webhook registration repository.

Provides a durable, file-based implementation of :class:`WebhookRepository`
using the standard library ``sqlite3`` module.  Named with the ``pg_`` prefix to
reserve the filename for a future PostgreSQL implementation while providing the
SQLite stepping-stone that can run without an external database server.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Any


class SqliteWebhookRepository:
    """SQLite-backed implementation of the webhook registration repository protocol.

    Each webhook registration is stored as a row in the ``webhook_registrations``
    table keyed by its URL path.

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
            "CREATE TABLE IF NOT EXISTS webhook_registrations ("
            "  path TEXT PRIMARY KEY,"
            "  secret TEXT NOT NULL,"
            "  workflow_name TEXT NOT NULL,"
            "  created_at TEXT NOT NULL"
            ")"
        )
        self._conn.commit()

    # -- protocol methods -----------------------------------------------------

    def get_webhook(self, path: str) -> dict[str, Any] | None:
        """Get a webhook registration by path."""
        row = self._conn.execute(
            "SELECT path, secret, workflow_name, created_at "
            "FROM webhook_registrations WHERE path = ?",
            (path,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def register_webhook(self, path: str, secret: str, workflow_name: str) -> dict[str, Any]:
        """Register a webhook (insert-or-replace). Returns the registration record."""
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            "INSERT OR REPLACE INTO webhook_registrations "
            "(path, secret, workflow_name, created_at) VALUES (?, ?, ?, ?)",
            (path, secret, workflow_name, now),
        )
        self._conn.commit()
        return {
            "path": path,
            "secret": secret,
            "workflow_name": workflow_name,
            "created_at": now,
        }

    def unregister_webhook(self, path: str) -> bool:
        """Unregister a webhook. Returns True if found and removed."""
        cursor = self._conn.execute("DELETE FROM webhook_registrations WHERE path = ?", (path,))
        self._conn.commit()
        return cursor.rowcount > 0

    def list_webhooks(self) -> list[dict[str, Any]]:
        """List all registered webhooks."""
        rows = self._conn.execute(
            "SELECT path, secret, workflow_name, created_at FROM webhook_registrations"
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    # -- helpers --------------------------------------------------------------

    @staticmethod
    def _row_to_dict(
        row: tuple[str, str, str, str],
    ) -> dict[str, Any]:
        """Convert a database row tuple to a webhook dict."""
        return {
            "path": row[0],
            "secret": row[1],
            "workflow_name": row[2],
            "created_at": row[3],
        }

    # -- lifecycle ------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()
