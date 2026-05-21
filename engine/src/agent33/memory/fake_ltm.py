"""In-memory substitute for LongTermMemory -- no PostgreSQL needed.

Provides the same interface as :class:`LongTermMemory` but stores
records in a plain Python list with cosine-similarity search using
only the standard library (``math`` module).  Designed for integration
tests that need a real data-flow without infrastructure dependencies.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from agent33.memory.long_term import SearchResult


@dataclass
class _Record:
    """Internal storage record."""

    id: int
    content: str
    embedding: list[float]
    metadata: dict[str, Any]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors.

    Returns 0.0 when either vector has zero magnitude.
    """
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class FakeLongTermMemory:
    """In-memory long-term memory for integration tests.

    Drop-in replacement for :class:`LongTermMemory` that requires
    no database connection.  Records are stored in a list and search
    is performed via brute-force cosine similarity.
    """

    def __init__(self, embedding_dim: int = 384) -> None:
        self._records: list[_Record] = []
        self._next_id: int = 1
        self._embedding_dim = embedding_dim

    async def initialize(self) -> None:
        """No-op -- no database to initialise."""

    async def close(self) -> None:
        """No-op -- no connections to close."""

    async def store(
        self,
        content: str,
        embedding: list[float],
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Store text with its embedding.  Returns the record id."""
        record_id = self._next_id
        self._next_id += 1
        self._records.append(
            _Record(
                id=record_id,
                content=content,
                embedding=embedding,
                metadata=metadata or {},
            )
        )
        return record_id

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
    ) -> list[SearchResult]:
        """Find the *top_k* most similar records by cosine similarity."""
        scored: list[tuple[float, _Record]] = []
        for record in self._records:
            score = _cosine_similarity(query_embedding, record.embedding)
            scored.append((score, record))

        scored.sort(key=lambda x: x[0], reverse=True)

        return [
            SearchResult(text=rec.content, score=score, metadata=rec.metadata)
            for score, rec in scored[:top_k]
        ]

    async def scan(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SearchResult]:
        """Paginated read of all stored content (sorted by id)."""
        ordered = sorted(self._records, key=lambda r: r.id)
        page = ordered[offset : offset + limit]
        return [SearchResult(text=r.content, score=0.0, metadata=r.metadata) for r in page]

    async def count(self) -> int:
        """Return total number of stored records."""
        return len(self._records)
