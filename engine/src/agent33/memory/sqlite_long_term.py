"""SQLite-backed long-term memory for lite mode (no PostgreSQL required)."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import aiosqlite

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS long_term_memory (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    tenant_id TEXT NOT NULL DEFAULT 'default'
);
"""

_CREATE_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
USING fts5(id UNINDEXED, content, metadata);
"""

_INSERT = """
INSERT INTO long_term_memory (id, content, metadata, created_at, tenant_id)
VALUES (?, ?, ?, ?, ?)
"""

_INSERT_FTS = """
INSERT INTO memory_fts (id, content, metadata) VALUES (?, ?, ?)
"""

_SELECT_BY_ID = """
SELECT id, content, metadata, created_at FROM long_term_memory WHERE id = ? AND tenant_id = ?
"""

_DELETE = """
DELETE FROM long_term_memory WHERE id = ? AND tenant_id = ?
"""

_DELETE_FTS = """
DELETE FROM memory_fts WHERE id = ?
"""

_SEARCH_FTS = """
SELECT m.id, m.content, m.metadata, m.created_at
FROM memory_fts f
JOIN long_term_memory m ON f.id = m.id
WHERE memory_fts MATCH ?
  AND m.tenant_id = ?
LIMIT ?
"""

_SEARCH_LIKE = """
SELECT id, content, metadata, created_at
FROM long_term_memory
WHERE (content LIKE ? OR metadata LIKE ?)
  AND tenant_id = ?
LIMIT ?
"""


class SQLiteLongTermMemory:
    """SQLite-backed long-term memory for AGENT33_MODE=lite.

    Uses FTS5 virtual tables for full-text search when available,
    falls back to LIKE-based search otherwise. No pgvector required.
    """

    def __init__(
        self,
        db_path: str | Path = ":memory:",
        tenant_id: str = "default",
    ) -> None:
        self._db_path = str(db_path)
        self._tenant_id = tenant_id
        self._db: aiosqlite.Connection | None = None
        self._fts_available = False

    async def initialize(self) -> None:
        """Open the database and create tables."""
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute(_CREATE_TABLE)
        try:
            await self._db.execute(_CREATE_FTS)
            self._fts_available = True
        except Exception:
            self._fts_available = False
            logger.debug("FTS5 not available, falling back to LIKE search")
        await self._db.commit()

    async def store(self, content: str, metadata: dict[str, Any]) -> str:
        """Store a memory entry, returning its ID."""
        assert self._db is not None, "Call initialize() first"
        memory_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        metadata_json = json.dumps(metadata)
        await self._db.execute(_INSERT, (memory_id, content, metadata_json, now, self._tenant_id))
        if self._fts_available:
            await self._db.execute(_INSERT_FTS, (memory_id, content, metadata_json))
        await self._db.commit()
        return memory_id

    async def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search memories by keyword. Uses FTS5 if available, LIKE otherwise."""
        assert self._db is not None, "Call initialize() first"
        rows: list[sqlite3.Row] = []
        if self._fts_available:
            try:
                # FTS5 requires escaping double-quotes in query
                safe_query = query.replace('"', '""')
                async with self._db.execute(
                    _SEARCH_FTS, (f'"{safe_query}"', self._tenant_id, limit)
                ) as cursor:
                    rows = list(await cursor.fetchall())
            except Exception:
                rows = []

        if not rows:
            pattern = f"%{query}%"
            async with self._db.execute(
                _SEARCH_LIKE, (pattern, pattern, self._tenant_id, limit)
            ) as cursor:
                rows = list(await cursor.fetchall())

        return [
            {
                "id": row[0],
                "content": row[1],
                "metadata": json.loads(row[2]),
                "created_at": row[3],
            }
            for row in rows
        ]

    async def get(self, memory_id: str) -> dict[str, Any] | None:
        """Retrieve a single memory by ID."""
        assert self._db is not None, "Call initialize() first"
        async with self._db.execute(_SELECT_BY_ID, (memory_id, self._tenant_id)) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "content": row[1],
            "metadata": json.loads(row[2]),
            "created_at": row[3],
        }

    async def delete(self, memory_id: str) -> bool:
        """Delete a memory by ID. Returns True if it existed."""
        assert self._db is not None, "Call initialize() first"
        async with self._db.execute(
            "SELECT id FROM long_term_memory WHERE id = ? AND tenant_id = ?",
            (memory_id, self._tenant_id),
        ) as cursor:
            exists = await cursor.fetchone() is not None
        if exists:
            await self._db.execute(_DELETE, (memory_id, self._tenant_id))
            if self._fts_available:
                await self._db.execute(_DELETE_FTS, (memory_id,))
            await self._db.commit()
        return exists

    async def close(self) -> None:
        """Close the database connection."""
        if self._db is not None:
            await self._db.close()
            self._db = None
