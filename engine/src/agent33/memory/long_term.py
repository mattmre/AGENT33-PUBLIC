"""Long-term memory backed by pgvector for semantic search."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

try:
    from sqlalchemy import Column, DateTime, Integer, Text, text
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.orm import DeclarativeBase

    _SQLALCHEMY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SQLALCHEMY_AVAILABLE = False
    # Placeholders so the module-level class bodies below don't crash at import.
    Column = None  # type: ignore[misc,assignment]
    DateTime = None  # type: ignore[misc,assignment]
    Integer = None  # type: ignore[misc,assignment]
    Text = None  # type: ignore[misc,assignment]
    text = None  # type: ignore[assignment]
    JSONB = None  # type: ignore[misc,assignment]
    async_sessionmaker = None  # type: ignore[misc,assignment]
    create_async_engine = None  # type: ignore[assignment]

    class DeclarativeBase:  # type: ignore[no-redef]
        pass


from agent33.observability.query_profiling import track_query

try:
    from pgvector.sqlalchemy import Vector
except ImportError:  # pragma: no cover
    Vector = None


class _Base(DeclarativeBase):
    pass


class MemoryRecord(_Base):
    """A stored memory with embedding vector."""

    __tablename__ = "memory_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    content = Column(Text, nullable=False)
    # Dimension is set at migration time; use unparameterized Vector() for ORM
    # mapping so that any dimension is accepted for read/write.
    embedding = Column(Vector() if Vector is not None else Text, nullable=False)
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )


@dataclass
class SearchResult:
    """A single search result from long-term memory."""

    text: str
    score: float
    metadata: dict[str, Any]


class LongTermMemory:
    """Semantic search over stored memories using pgvector."""

    def __init__(
        self,
        database_url: str,
        embedding_dim: int = 768,
        *,
        pool_size: int = 10,
        max_overflow: int = 20,
        pool_pre_ping: bool = True,
        pool_recycle: int = 1800,
    ) -> None:
        if not _SQLALCHEMY_AVAILABLE:
            raise RuntimeError(
                "PostgreSQL dependencies are not installed. "
                "Install with: pip install agent33[standard]"
            )
        self._engine = create_async_engine(
            database_url,
            echo=False,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=pool_pre_ping,
            pool_recycle=pool_recycle,
        )
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)
        self._embedding_dim = embedding_dim

    async def initialize(self) -> None:
        """Create tables and enable pgvector extension."""
        async with self._engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(_Base.metadata.create_all)

    async def store(
        self,
        content: str,
        embedding: list[float],
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Store text with its embedding. Returns the record id."""
        record = MemoryRecord(
            content=content,
            embedding=embedding,
            metadata_=metadata or {},
        )
        async with (
            track_query("memory_store", table="memory_records"),
            self._session_factory() as session,
            session.begin(),
        ):
            session.add(record)
            await session.flush()
            record_id: int = record.id  # type: ignore[assignment]
        return record_id

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
    ) -> list[SearchResult]:
        """Find the *top_k* most similar memories by cosine distance."""
        embedding_literal = f"[{','.join(str(v) for v in query_embedding)}]"
        sql = text(
            "SELECT content, metadata, "
            "1 - (embedding <=> :emb::vector) AS score "
            "FROM memory_records "
            "ORDER BY embedding <=> :emb::vector "
            "LIMIT :k"
        )
        async with (
            track_query("memory_search", table="memory_records"),
            self._session_factory() as session,
        ):
            result = await session.execute(sql, {"emb": embedding_literal, "k": top_k})
            rows = result.fetchall()
        return [
            SearchResult(text=row[0], score=float(row[2]), metadata=row[1] or {}) for row in rows
        ]

    async def scan(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SearchResult]:
        """Paginated read of all stored content for BM25 warm-up.

        Returns SearchResult objects (text, score=0.0, metadata) ordered by id.
        """
        sql = text(
            "SELECT content, metadata FROM memory_records ORDER BY id LIMIT :limit OFFSET :offset"
        )
        async with (
            track_query("memory_scan", table="memory_records"),
            self._session_factory() as session,
        ):
            result = await session.execute(sql, {"limit": limit, "offset": offset})
            rows = result.fetchall()
        return [SearchResult(text=row[0], score=0.0, metadata=row[1] or {}) for row in rows]

    async def count(self) -> int:
        """Return total number of stored memory records."""
        sql = text("SELECT COUNT(*) FROM memory_records")
        async with self._session_factory() as session:
            result = await session.execute(sql)
            row = result.fetchone()
        return row[0] if row else 0

    async def close(self) -> None:
        """Dispose of the engine connection pool."""
        await self._engine.dispose()
