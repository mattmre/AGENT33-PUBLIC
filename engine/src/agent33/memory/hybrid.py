"""Hybrid search combining BM25 keyword and vector semantic retrieval.

Uses Reciprocal Rank Fusion (RRF) to merge results from both scoring
systems without needing explicit score normalization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agent33.observability.query_profiling import track_query

if TYPE_CHECKING:
    from agent33.memory.bm25 import BM25Index
    from agent33.memory.embeddings import EmbeddingProvider
    from agent33.memory.long_term import LongTermMemory


# ── Default RRF constant ─────────────────────────────────────────────
# Higher k dampens the rank influence; 60 is the standard from the
# original RRF paper (Cormack et al., 2009).
_RRF_K = 60


@dataclass
class HybridResult:
    """A single result from hybrid search."""

    text: str
    score: float
    vector_score: float = 0.0
    bm25_score: float = 0.0
    vector_rank: int = 0
    bm25_rank: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class HybridSearcher:
    """Combines pgvector semantic search with BM25 keyword search.

    Uses Reciprocal Rank Fusion (RRF) to merge the two ranked lists
    without requiring score normalization.

    Parameters
    ----------
    long_term_memory:
        The pgvector-backed semantic memory store.
    embedding_provider:
        Used to embed queries for vector search.
    bm25_index:
        The in-memory BM25 keyword index.
    vector_weight:
        Weight for the vector RRF score (0.0 to 1.0).  The BM25
        weight is ``1 - vector_weight``.  Default 0.7.
    rrf_k:
        Rank fusion constant.  Default 60.
    """

    def __init__(
        self,
        long_term_memory: LongTermMemory,
        embedding_provider: EmbeddingProvider,
        bm25_index: BM25Index,
        vector_weight: float = 0.7,
        rrf_k: int = _RRF_K,
    ) -> None:
        self._memory = long_term_memory
        self._embedder = embedding_provider
        self._bm25 = bm25_index
        self._vector_weight = max(0.0, min(1.0, vector_weight))
        self._bm25_weight = 1.0 - self._vector_weight
        self._rrf_k = max(1, rrf_k)

    async def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        vector_only: bool = False,
        bm25_only: bool = False,
    ) -> list[HybridResult]:
        """Search using hybrid BM25 + vector retrieval.

        Parameters
        ----------
        query:
            The search query.
        top_k:
            Number of results to return.
        vector_only:
            Use only vector search (disable BM25).
        bm25_only:
            Use only BM25 search (disable vector).
        """
        async with track_query("hybrid_search", table="memory_records"):
            # Fetch candidates from both systems (request more than top_k
            # so the fusion has a richer candidate pool).
            fetch_k = top_k * 3

            vector_results: list[HybridResult] = []
            bm25_results: list[HybridResult] = []

            if not bm25_only:
                query_embedding = await self._embedder.embed(query)
                raw_vector = await self._memory.search(query_embedding, top_k=fetch_k)
                vector_results = [
                    HybridResult(
                        text=r.text,
                        score=0.0,
                        vector_score=r.score,
                        metadata=r.metadata,
                    )
                    for r in raw_vector
                ]

            if not vector_only and self._bm25.size > 0:
                raw_bm25 = self._bm25.search(query, top_k=fetch_k)
                bm25_results = [
                    HybridResult(
                        text=r.text,
                        score=0.0,
                        bm25_score=r.score,
                        metadata=r.metadata,
                    )
                    for r in raw_bm25
                ]

            if vector_only or self._bm25.size == 0:
                # Pure vector mode.
                for i, result in enumerate(vector_results):
                    result.vector_rank = i + 1
                    result.score = result.vector_score
                return vector_results[:top_k]

            if bm25_only:
                # Pure BM25 mode.
                for i, result in enumerate(bm25_results):
                    result.bm25_rank = i + 1
                    result.score = result.bm25_score
                return bm25_results[:top_k]

            # ── Reciprocal Rank Fusion ───────────────────────────────
            return self._fuse(vector_results, bm25_results, top_k)

    def _fuse(
        self,
        vector_results: list[HybridResult],
        bm25_results: list[HybridResult],
        top_k: int,
    ) -> list[HybridResult]:
        """Merge two ranked lists using weighted RRF."""
        # Build a map keyed by text content for deduplication.
        merged: dict[str, HybridResult] = {}

        for rank, result in enumerate(vector_results, 1):
            key = result.text
            if key not in merged:
                merged[key] = HybridResult(
                    text=result.text,
                    score=0.0,
                    vector_score=result.vector_score,
                    metadata=result.metadata,
                )
            merged[key].vector_rank = rank
            merged[key].vector_score = result.vector_score

        for rank, result in enumerate(bm25_results, 1):
            key = result.text
            if key not in merged:
                merged[key] = HybridResult(
                    text=result.text,
                    score=0.0,
                    bm25_score=result.bm25_score,
                    metadata=result.metadata,
                )
            merged[key].bm25_rank = rank
            merged[key].bm25_score = result.bm25_score

        # Compute RRF scores.
        for result in merged.values():
            v_rrf = 0.0
            b_rrf = 0.0
            if result.vector_rank > 0:
                v_rrf = 1.0 / (self._rrf_k + result.vector_rank)
            if result.bm25_rank > 0:
                b_rrf = 1.0 / (self._rrf_k + result.bm25_rank)
            result.score = self._vector_weight * v_rrf + self._bm25_weight * b_rrf

        # Sort by fused score descending.
        ranked = sorted(merged.values(), key=lambda r: r.score, reverse=True)
        return ranked[:top_k]
