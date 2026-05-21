"""LRU embedding cache -- avoids re-embedding duplicate text.

Wraps an :class:`EmbeddingProvider` and caches results keyed by
a SHA-256 hash of the input text.  Thread-safe via ``asyncio.Lock``.

When ``compressor`` is provided, embeddings are stored in quantized form
(typically 8x smaller at 4 bits/coord) and decompressed on cache hits.
This trades a small amount of reconstruction error for dramatically
higher cache capacity at the same memory budget.

The lock only protects the OrderedDict structure (fast dict reads/writes).
CPU-bound compress/decompress work runs outside the lock via
``run_in_executor`` to avoid blocking the event loop.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent33.memory.embeddings import EmbeddingProvider
    from agent33.memory.quantization import TurboQuantCompressor


def _text_key(text: str) -> str:
    """SHA-256 hash of *text* used as cache key."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class EmbeddingCache:
    """LRU cache wrapping an :class:`EmbeddingProvider`.

    Parameters
    ----------
    provider:
        The underlying embedding provider to delegate cache misses to.
    max_size:
        Maximum number of embeddings to hold in cache (default 1024).
    compressor:
        Optional :class:`TurboQuantCompressor`.  When provided, embeddings
        are stored quantized (~8x smaller) and decompressed on retrieval.
    """

    def __init__(
        self,
        provider: EmbeddingProvider,
        max_size: int = 1024,
        compressor: TurboQuantCompressor | None = None,
    ) -> None:
        self._provider = provider
        self._max_size = max(1, max_size)
        # Values are either list[float] (uncompressed) or QuantizedVector.
        self._cache: OrderedDict[str, Any] = OrderedDict()
        self._lock = asyncio.Lock()
        self._hits: int = 0
        self._misses: int = 0
        self._compressor = compressor

    # -- Single embedding -------------------------------------------------

    async def embed(self, text: str) -> list[float]:
        """Return embedding for *text*, serving from cache when possible."""
        key = _text_key(text)

        # Fast cache lookup under lock (dict read only).
        cached: Any = None
        async with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._hits += 1
                cached = self._cache[key]

        if cached is not None:
            # Decompress outside lock -- CPU-bound work in executor.
            if self._compressor is not None:
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(None, self._compressor.decompress, cached)
            return cached  # type: ignore[no-any-return]

        # Cache miss -- call the underlying provider (already outside lock).
        embedding = await self._provider.embed(text)

        # Compress outside lock -- CPU-bound work in executor.
        to_store: Any = embedding
        if self._compressor is not None:
            loop = asyncio.get_event_loop()
            to_store = await loop.run_in_executor(None, self._compressor.compress, embedding)

        # Store under lock (dict write only).
        async with self._lock:
            self._cache[key] = to_store
            self._cache.move_to_end(key)
            self._misses += 1
            self._evict()

        return embedding

    # -- Batch embedding --------------------------------------------------

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return embeddings for *texts*, using cache where possible.

        Only calls the underlying provider for texts not already cached.
        Results are returned in the same order as the input.
        """
        if not texts:
            return []

        keys = [_text_key(t) for t in texts]
        results: list[list[float] | None] = [None] * len(texts)
        miss_indices: list[int] = []
        miss_texts: list[str] = []
        cached_items: list[tuple[int, Any]] = []

        # Lookup phase under lock (dict reads only).
        async with self._lock:
            for i, key in enumerate(keys):
                if key in self._cache:
                    self._cache.move_to_end(key)
                    cached_items.append((i, self._cache[key]))
                    self._hits += 1
                else:
                    miss_indices.append(i)
                    miss_texts.append(texts[i])

        # Decompress cached items outside lock.
        for i, cached in cached_items:
            if self._compressor is not None:
                loop = asyncio.get_event_loop()
                results[i] = await loop.run_in_executor(None, self._compressor.decompress, cached)
            else:
                results[i] = cached

        if miss_texts:
            new_embeddings = await self._provider.embed_batch(miss_texts)

            # Compress new embeddings outside lock.
            to_store_list: list[Any] = []
            if self._compressor is not None:
                loop = asyncio.get_event_loop()
                for emb in new_embeddings:
                    compressed = await loop.run_in_executor(None, self._compressor.compress, emb)
                    to_store_list.append(compressed)
            else:
                to_store_list = list(new_embeddings)

            # Store under lock (dict writes only).
            async with self._lock:
                for j, idx in enumerate(miss_indices):
                    key = keys[idx]
                    self._cache[key] = to_store_list[j]
                    self._cache.move_to_end(key)
                    results[idx] = new_embeddings[j]
                    self._misses += 1
                self._evict()

        return [r for r in results if r is not None]

    # -- Introspection ----------------------------------------------------

    @property
    def size(self) -> int:
        """Number of embeddings currently cached."""
        return len(self._cache)

    @property
    def hits(self) -> int:
        """Total cache hits."""
        return self._hits

    @property
    def misses(self) -> int:
        """Total cache misses."""
        return self._misses

    @property
    def hit_rate(self) -> float:
        """Cache hit rate as a fraction [0.0, 1.0]."""
        total = self._hits + self._misses
        if total == 0:
            return 0.0
        return self._hits / total

    def clear(self) -> None:
        """Evict all cached embeddings."""
        self._cache.clear()

    # -- Delegate close to underlying provider ----------------------------

    async def close(self) -> None:
        """Close the underlying embedding provider."""
        await self._provider.close()

    # -- Internal ---------------------------------------------------------

    def _evict(self) -> None:
        """Remove oldest entries until cache is within *max_size*."""
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)
