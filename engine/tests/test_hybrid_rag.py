"""Tests for hybrid RAG: BM25 scoring, hybrid search, token-aware chunking,
embedding cache, and updated RAG pipeline.

Every test asserts on real behavior — BM25 ranking correctness,
cache hit/miss semantics, chunk boundary placement, hybrid fusion
ordering, and RAG prompt formatting.
"""

from __future__ import annotations

import math
from unittest.mock import AsyncMock

import pytest

from agent33.memory.bm25 import BM25Index, tokenize
from agent33.memory.cache import EmbeddingCache
from agent33.memory.hybrid import HybridResult, HybridSearcher
from agent33.memory.ingestion import (
    DocumentIngester,
    TokenAwareChunker,
    _estimate_tokens,
)
from agent33.memory.long_term import SearchResult
from agent33.memory.rag import RAGPipeline

# ═══════════════════════════════════════════════════════════════════════
# BM25 Tests
# ═══════════════════════════════════════════════════════════════════════


class TestTokenize:
    """Test BM25 tokenizer."""

    def test_basic_tokenization(self) -> None:
        tokens = tokenize("Hello World")
        assert tokens == ["hello", "world"]

    def test_stopword_removal(self) -> None:
        tokens = tokenize("the quick brown fox is in the box")
        assert "the" not in tokens
        assert "is" not in tokens
        assert "in" not in tokens
        assert "quick" in tokens
        assert "brown" in tokens
        assert "fox" in tokens
        assert "box" in tokens

    def test_keep_stopwords(self) -> None:
        tokens = tokenize("the cat is here", remove_stopwords=False)
        assert "the" in tokens
        assert "is" in tokens

    def test_punctuation_stripped(self) -> None:
        tokens = tokenize("hello, world! foo-bar_baz")
        assert "hello" in tokens
        assert "world" in tokens
        # hyphenated words are split
        assert "foo" in tokens
        assert "bar_baz" in tokens

    def test_empty_text(self) -> None:
        assert tokenize("") == []

    def test_only_stopwords(self) -> None:
        assert tokenize("the is a an") == []


class TestBM25Index:
    """Test BM25 scoring engine."""

    def test_empty_index_returns_empty(self) -> None:
        idx = BM25Index()
        results = idx.search("hello")
        assert results == []

    def test_single_document_match(self) -> None:
        idx = BM25Index()
        idx.add_document("python programming language")
        results = idx.search("python")
        assert len(results) == 1
        assert results[0].score > 0
        assert "python" in results[0].text

    def test_no_match(self) -> None:
        idx = BM25Index()
        idx.add_document("python programming language")
        results = idx.search("javascript")
        assert results == []

    def test_ranking_order(self) -> None:
        """Document with more query term occurrences ranks higher."""
        idx = BM25Index()
        idx.add_document("python is great")
        idx.add_document("python python python is the best python")
        results = idx.search("python")
        assert len(results) == 2
        # Second doc has more "python" occurrences → higher score.
        assert results[0].score > results[1].score
        assert "best" in results[0].text

    def test_idf_weighting(self) -> None:
        """Rare terms get higher IDF weight than common terms."""
        idx = BM25Index()
        # "machine" appears in both, "quantum" only in second.
        idx.add_document("machine learning basics")
        idx.add_document("quantum machine computing")
        # Search for "quantum" — only doc 2 has it, so it gets boosted.
        results = idx.search("quantum")
        assert len(results) == 1
        assert "quantum" in results[0].text

    def test_top_k_limits_results(self) -> None:
        idx = BM25Index()
        for i in range(20):
            idx.add_document(f"document number {i} about python")
        results = idx.search("python", top_k=3)
        assert len(results) == 3

    def test_add_documents_bulk(self) -> None:
        idx = BM25Index()
        indices = idx.add_documents(
            [
                ("first doc", None),
                ("second doc", {"key": "value"}),
            ]
        )
        assert indices == [0, 1]
        assert idx.size == 2

    def test_metadata_preserved(self) -> None:
        idx = BM25Index()
        idx.add_document("test doc", {"source": "unit_test"})
        results = idx.search("test")
        assert results[0].metadata == {"source": "unit_test"}

    def test_clear(self) -> None:
        idx = BM25Index()
        idx.add_document("hello world")
        assert idx.size == 1
        idx.clear()
        assert idx.size == 0
        assert idx.search("hello") == []

    def test_doc_index_returned(self) -> None:
        idx = BM25Index()
        idx.add_document("alpha")
        idx.add_document("beta")
        idx.add_document("alpha beta gamma")
        results = idx.search("alpha")
        # doc_index should be one of 0, 2 (both contain "alpha").
        doc_indices = {r.doc_index for r in results}
        assert 0 in doc_indices
        assert 2 in doc_indices

    def test_query_with_only_stopwords(self) -> None:
        idx = BM25Index()
        idx.add_document("important data here")
        results = idx.search("the is a")
        assert results == []

    def test_multi_term_query(self) -> None:
        idx = BM25Index()
        idx.add_document("machine learning algorithms")
        idx.add_document("deep learning neural networks")
        idx.add_document("machine translation systems")
        results = idx.search("machine learning")
        # "machine learning algorithms" matches both terms → highest.
        assert "machine learning" in results[0].text.lower()

    def test_length_normalization(self) -> None:
        """Shorter docs with same term freq get boosted by BM25's b param."""
        idx = BM25Index(b=0.75)
        # Short doc with "python" once.
        idx.add_document("python")
        # Long doc with "python" once plus filler.
        idx.add_document("python " + " ".join(["filler"] * 100))
        results = idx.search("python")
        assert len(results) == 2
        # The short doc should score higher due to length normalization.
        assert len(results[0].text) < len(results[1].text)

    def test_custom_k1_b_params(self) -> None:
        idx = BM25Index(k1=2.0, b=0.5)
        idx.add_document("test document alpha")
        idx.add_document("test document beta")
        results = idx.search("alpha")
        assert len(results) == 1
        assert results[0].score > 0


# ═══════════════════════════════════════════════════════════════════════
# Embedding Cache Tests
# ═══════════════════════════════════════════════════════════════════════


class TestEmbeddingCache:
    """Test LRU embedding cache."""

    @pytest.mark.asyncio
    async def test_cache_hit(self) -> None:
        """Second call for same text returns cached result."""
        mock_provider = AsyncMock()
        mock_provider.embed.return_value = [0.1, 0.2, 0.3]

        cache = EmbeddingCache(mock_provider, max_size=10)
        result1 = await cache.embed("hello")
        result2 = await cache.embed("hello")

        assert result1 == result2
        # Provider called only once.
        assert mock_provider.embed.call_count == 1
        assert cache.hits == 1
        assert cache.misses == 1

    @pytest.mark.asyncio
    async def test_cache_miss(self) -> None:
        """Different texts are separate cache entries."""
        mock_provider = AsyncMock()
        mock_provider.embed.side_effect = [
            [0.1, 0.2],
            [0.3, 0.4],
        ]

        cache = EmbeddingCache(mock_provider, max_size=10)
        r1 = await cache.embed("hello")
        r2 = await cache.embed("world")

        assert r1 != r2
        assert mock_provider.embed.call_count == 2
        assert cache.misses == 2
        assert cache.hits == 0

    @pytest.mark.asyncio
    async def test_lru_eviction(self) -> None:
        """Oldest entry evicted when max_size exceeded."""
        mock_provider = AsyncMock()
        call_count = 0

        async def mock_embed(text: str) -> list[float]:
            nonlocal call_count
            call_count += 1
            return [float(call_count)]

        mock_provider.embed.side_effect = mock_embed

        cache = EmbeddingCache(mock_provider, max_size=2)
        await cache.embed("a")  # miss → cache: {a}
        await cache.embed("b")  # miss → cache: {a, b}
        await cache.embed("c")  # miss → evict a → cache: {b, c}

        assert cache.size == 2
        assert cache.misses == 3

        # "b" should still be cached (was not evicted).
        await cache.embed("b")
        assert cache.hits == 1
        assert mock_provider.embed.call_count == 3  # no new call for "b"

        # "a" was evicted — should trigger a new provider call.
        await cache.embed("a")
        assert mock_provider.embed.call_count == 4

    @pytest.mark.asyncio
    async def test_batch_caching(self) -> None:
        """Batch embed uses cache for hits and provider for misses only."""
        mock_provider = AsyncMock()
        mock_provider.embed.return_value = [0.1, 0.2]
        mock_provider.embed_batch.return_value = [[0.5, 0.6]]

        cache = EmbeddingCache(mock_provider, max_size=10)
        # Prime cache with "hello".
        await cache.embed("hello")
        assert cache.misses == 1

        # Batch with one cached + one uncached.
        results = await cache.embed_batch(["hello", "world"])
        assert len(results) == 2
        assert results[0] == [0.1, 0.2]  # cached
        assert results[1] == [0.5, 0.6]  # from provider batch

        # Provider batch called with only the miss.
        mock_provider.embed_batch.assert_called_once_with(["world"])
        assert cache.hits == 1  # "hello" hit in batch
        assert cache.misses == 2  # embed("hello") miss + batch("world") miss

    @pytest.mark.asyncio
    async def test_batch_empty(self) -> None:
        mock_provider = AsyncMock()
        cache = EmbeddingCache(mock_provider, max_size=10)
        results = await cache.embed_batch([])
        assert results == []

    @pytest.mark.asyncio
    async def test_hit_rate(self) -> None:
        mock_provider = AsyncMock()
        mock_provider.embed.return_value = [0.1]

        cache = EmbeddingCache(mock_provider, max_size=10)
        assert cache.hit_rate == 0.0

        await cache.embed("a")  # miss
        await cache.embed("a")  # hit
        await cache.embed("a")  # hit
        assert cache.hit_rate == pytest.approx(2 / 3)

    @pytest.mark.asyncio
    async def test_clear(self) -> None:
        mock_provider = AsyncMock()
        mock_provider.embed.return_value = [0.1]

        cache = EmbeddingCache(mock_provider, max_size=10)
        await cache.embed("hello")
        assert cache.size == 1
        cache.clear()
        assert cache.size == 0

    @pytest.mark.asyncio
    async def test_close_delegates(self) -> None:
        mock_provider = AsyncMock()
        cache = EmbeddingCache(mock_provider)
        await cache.close()
        mock_provider.close.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════
# Token-Aware Chunking Tests
# ═══════════════════════════════════════════════════════════════════════


class TestTokenEstimation:
    """Test token estimation heuristic."""

    def test_estimate_tokens(self) -> None:
        assert _estimate_tokens("one two three") == math.ceil(3 * 1.3)

    def test_empty_string(self) -> None:
        assert _estimate_tokens("") == 0


class TestTokenAwareChunker:
    """Test token-aware chunking with sentence boundary preservation."""

    def test_empty_text(self) -> None:
        chunker = TokenAwareChunker(chunk_tokens=100)
        assert chunker.chunk_text("") == []
        assert chunker.chunk_text("   ") == []

    def test_small_text_single_chunk(self) -> None:
        chunker = TokenAwareChunker(chunk_tokens=1200)
        text = "This is a short sentence."
        chunks = chunker.chunk_text(text)
        assert len(chunks) == 1
        assert chunks[0].text == text
        assert chunks[0].metadata["strategy"] == "token_aware"

    def test_sentence_boundary_preservation(self) -> None:
        """Chunks split at sentence boundaries, not mid-sentence."""
        chunker = TokenAwareChunker(chunk_tokens=10, overlap_tokens=0)
        # Each sentence ~ 3 tokens. With chunk_tokens=10, we should
        # get ~3 sentences per chunk.
        sentences = [
            "First sentence here.",
            "Second sentence here.",
            "Third sentence here.",
            "Fourth sentence here.",
            "Fifth sentence here.",
            "Sixth sentence here.",
        ]
        text = " ".join(sentences)
        chunks = chunker.chunk_text(text)
        assert len(chunks) >= 2
        # Every chunk should end with a period (sentence boundary).
        for chunk in chunks:
            assert chunk.text.rstrip().endswith(".")

    def test_overlap_includes_previous_sentences(self) -> None:
        """Overlap window carries trailing sentences from previous chunk."""
        chunker = TokenAwareChunker(chunk_tokens=8, overlap_tokens=4)
        sentences = [
            "Alpha sentence.",
            "Beta sentence.",
            "Gamma sentence.",
            "Delta sentence.",
            "Epsilon sentence.",
        ]
        text = " ".join(sentences)
        chunks = chunker.chunk_text(text)
        assert len(chunks) >= 2
        # Check that some text from the end of chunk 0 appears at the
        # beginning of chunk 1 (overlap).
        if len(chunks) >= 2:
            # The last sentence of chunk 0 should appear in chunk 1.
            last_sentence_of_first = chunks[0].text.split(".")[-2].strip()
            if last_sentence_of_first:
                assert last_sentence_of_first in chunks[1].text

    def test_token_estimate_in_metadata(self) -> None:
        chunker = TokenAwareChunker(chunk_tokens=1200)
        text = "Some text here. Another sentence follows."
        chunks = chunker.chunk_text(text)
        assert len(chunks) == 1
        assert "tokens_est" in chunks[0].metadata
        assert chunks[0].metadata["tokens_est"] > 0

    def test_force_split_long_sentence(self) -> None:
        """A single sentence exceeding chunk_tokens is force-split by words."""
        chunker = TokenAwareChunker(chunk_tokens=5, overlap_tokens=0)
        # Generate a very long single sentence (no periods).
        long_sentence = " ".join([f"word{i}" for i in range(50)])
        chunks = chunker.chunk_text(long_sentence)
        assert len(chunks) > 1
        for chunk in chunks:
            assert chunk.metadata["strategy"] in ("token_aware", "token_aware_forced")

    def test_markdown_chunking(self) -> None:
        chunker = TokenAwareChunker(chunk_tokens=20, overlap_tokens=0)
        md = (
            "# Heading One\n\n"
            "Content of section one. More text here.\n\n"
            "# Heading Two\n\n"
            "Content of section two. Even more text here.\n"
        )
        chunks = chunker.chunk_markdown(md)
        assert len(chunks) >= 2
        assert chunks[0].metadata["source"] == "markdown"

    def test_markdown_empty(self) -> None:
        chunker = TokenAwareChunker(chunk_tokens=100)
        assert chunker.chunk_markdown("") == []

    def test_chunk_indices_sequential(self) -> None:
        chunker = TokenAwareChunker(chunk_tokens=10, overlap_tokens=0)
        text = "First. Second. Third. Fourth. Fifth. Sixth. Seventh."
        chunks = chunker.chunk_text(text)
        for i, chunk in enumerate(chunks):
            assert chunk.index == i

    def test_default_parameters(self) -> None:
        chunker = TokenAwareChunker()
        assert chunker._chunk_tokens == 1200
        assert chunker._overlap_tokens == 100


class TestDocumentIngesterBackcompat:
    """Verify the legacy DocumentIngester still works unchanged."""

    def test_char_based_chunking(self) -> None:
        ingester = DocumentIngester()
        text = "x" * 1500
        chunks = ingester.ingest_text(text, chunk_size=500, overlap=50)
        assert len(chunks) >= 3
        assert len(chunks[0].text) == 500

    def test_markdown_chunking(self) -> None:
        ingester = DocumentIngester()
        md = "# Title\n\nContent\n\n# Title 2\n\nMore content"
        chunks = ingester.ingest_markdown(md, chunk_size=500)
        assert len(chunks) >= 2


# ═══════════════════════════════════════════════════════════════════════
# Hybrid Search Tests
# ═══════════════════════════════════════════════════════════════════════


class TestHybridSearcher:
    """Test hybrid BM25 + vector search with RRF."""

    def _make_searcher(
        self,
        vector_results: list[SearchResult],
        bm25_docs: list[tuple[str, dict]],
        vector_weight: float = 0.7,
    ) -> tuple[HybridSearcher, AsyncMock, AsyncMock]:
        mock_memory = AsyncMock()
        mock_memory.search.return_value = vector_results

        mock_embedder = AsyncMock()
        mock_embedder.embed.return_value = [0.1] * 1536

        bm25 = BM25Index()
        for text, meta in bm25_docs:
            bm25.add_document(text, meta)

        searcher = HybridSearcher(
            long_term_memory=mock_memory,
            embedding_provider=mock_embedder,
            bm25_index=bm25,
            vector_weight=vector_weight,
        )
        return searcher, mock_memory, mock_embedder

    @pytest.mark.asyncio
    async def test_hybrid_merges_both_sources(self) -> None:
        """Results from both BM25 and vector appear in output."""
        vector_hits = [
            SearchResult(text="vector match about python", score=0.9, metadata={}),
        ]
        bm25_docs = [
            ("bm25 match about python programming", {}),
            ("unrelated document about cooking", {}),
        ]
        searcher, _, _ = self._make_searcher(vector_hits, bm25_docs)
        results = await searcher.search("python", top_k=5)
        texts = [r.text for r in results]
        assert any("vector match" in t for t in texts)
        assert any("bm25 match" in t for t in texts)

    @pytest.mark.asyncio
    async def test_deduplication(self) -> None:
        """Same text from both sources is deduplicated."""
        shared_text = "python is great for data science"
        vector_hits = [
            SearchResult(text=shared_text, score=0.85, metadata={}),
        ]
        bm25_docs = [
            (shared_text, {}),
        ]
        searcher, _, _ = self._make_searcher(vector_hits, bm25_docs)
        results = await searcher.search("python data", top_k=5)
        # Should appear only once despite being in both result sets.
        assert sum(1 for r in results if r.text == shared_text) == 1
        # The deduplicated result should have both ranks set.
        deduped = [r for r in results if r.text == shared_text][0]
        assert deduped.vector_rank > 0
        assert deduped.bm25_rank > 0

    @pytest.mark.asyncio
    async def test_vector_only_mode(self) -> None:
        """vector_only=True skips BM25."""
        vector_hits = [
            SearchResult(text="vector result", score=0.8, metadata={}),
        ]
        bm25_docs = [("bm25 result about something", {})]
        searcher, _, _ = self._make_searcher(vector_hits, bm25_docs)
        results = await searcher.search("test", top_k=5, vector_only=True)
        texts = [r.text for r in results]
        assert "vector result" in texts
        assert "bm25 result about something" not in texts

    @pytest.mark.asyncio
    async def test_bm25_only_mode(self) -> None:
        """bm25_only=True skips vector search."""
        vector_hits = [
            SearchResult(text="vector result", score=0.8, metadata={}),
        ]
        bm25_docs = [("keyword match document", {})]
        searcher, mock_memory, mock_embedder = self._make_searcher(vector_hits, bm25_docs)
        results = await searcher.search("keyword match", top_k=5, bm25_only=True)
        # Embedder should NOT have been called.
        mock_embedder.embed.assert_not_called()
        mock_memory.search.assert_not_called()
        assert len(results) >= 1
        assert results[0].text == "keyword match document"

    @pytest.mark.asyncio
    async def test_empty_bm25_index_falls_back_to_vector(self) -> None:
        """When BM25 index is empty, returns pure vector results."""
        vector_hits = [
            SearchResult(text="only vector", score=0.7, metadata={}),
        ]
        searcher, _, _ = self._make_searcher(vector_hits, bm25_docs=[])
        results = await searcher.search("test", top_k=5)
        assert len(results) == 1
        assert results[0].text == "only vector"

    @pytest.mark.asyncio
    async def test_top_k_limit(self) -> None:
        vector_hits = [
            SearchResult(text=f"vec{i}", score=0.9 - i * 0.1, metadata={}) for i in range(10)
        ]
        bm25_docs = [(f"bm25doc{i} search term", {}) for i in range(10)]
        searcher, _, _ = self._make_searcher(vector_hits, bm25_docs)
        results = await searcher.search("search term", top_k=3)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_rrf_scoring(self) -> None:
        """Document ranked #1 by both systems gets highest RRF score."""
        vector_hits = [
            SearchResult(text="top doc", score=0.95, metadata={}),
            SearchResult(text="second doc", score=0.80, metadata={}),
        ]
        bm25_docs = [
            ("top doc", {}),
            ("second doc", {}),
        ]
        searcher, _, _ = self._make_searcher(vector_hits, bm25_docs, vector_weight=0.5)
        results = await searcher.search("top doc", top_k=5)
        # "top doc" should be ranked #1 by both → highest combined score.
        assert results[0].text == "top doc"

    @pytest.mark.asyncio
    async def test_vector_weight_influence(self) -> None:
        """Higher vector_weight favors vector-ranked results.

        Both docs match the BM25 query, but the vector search ranks
        them differently.  With high vector_weight, vector ranking
        dominates the final order.
        """
        vector_hits = [
            SearchResult(text="alpha search topic", score=0.95, metadata={}),
            SearchResult(text="beta search topic", score=0.50, metadata={}),
        ]
        bm25_docs = [
            # BM25 has "beta" ranked higher due to more query terms.
            ("beta search topic search search", {}),
            ("alpha search topic", {}),
        ]
        # With vector_weight=0.9, vector ranking (alpha #1) dominates.
        searcher, _, _ = self._make_searcher(vector_hits, bm25_docs, vector_weight=0.9)
        results = await searcher.search("search topic", top_k=2)
        assert results[0].text == "alpha search topic"


# ═══════════════════════════════════════════════════════════════════════
# Updated RAG Pipeline Tests
# ═══════════════════════════════════════════════════════════════════════


class TestRAGPipeline:
    """Test the RAG pipeline with both vector-only and hybrid modes."""

    @pytest.mark.asyncio
    async def test_vector_only_query(self) -> None:
        """RAG with no hybrid searcher uses vector-only path."""
        mock_embedder = AsyncMock()
        mock_embedder.embed.return_value = [0.1] * 1536

        mock_memory = AsyncMock()
        mock_memory.search.return_value = [
            SearchResult(text="Relevant context", score=0.8, metadata={}),
        ]

        pipeline = RAGPipeline(
            embedding_provider=mock_embedder,
            long_term_memory=mock_memory,
        )
        result = await pipeline.query("What is python?")
        assert "Relevant context" in result.augmented_prompt
        assert "---Context---" in result.augmented_prompt
        assert len(result.sources) == 1
        assert result.sources[0].retrieval_method == "vector"

    @pytest.mark.asyncio
    async def test_vector_no_results(self) -> None:
        """No results above threshold returns unaugmented prompt."""
        mock_embedder = AsyncMock()
        mock_embedder.embed.return_value = [0.1] * 1536
        mock_memory = AsyncMock()
        mock_memory.search.return_value = [
            SearchResult(text="Low quality", score=0.1, metadata={}),
        ]

        pipeline = RAGPipeline(
            embedding_provider=mock_embedder,
            long_term_memory=mock_memory,
            similarity_threshold=0.5,
        )
        result = await pipeline.query("test query")
        assert result.augmented_prompt == "test query"
        assert result.sources == []

    @pytest.mark.asyncio
    async def test_hybrid_query(self) -> None:
        """RAG with hybrid searcher uses the hybrid path."""
        mock_embedder = AsyncMock()
        mock_memory = AsyncMock()

        mock_hybrid = AsyncMock()
        mock_hybrid.search.return_value = [
            HybridResult(
                text="Hybrid result",
                score=0.5,
                vector_score=0.8,
                bm25_score=0.3,
                metadata={"source": "test"},
            ),
        ]

        pipeline = RAGPipeline(
            embedding_provider=mock_embedder,
            long_term_memory=mock_memory,
            hybrid_searcher=mock_hybrid,
        )
        result = await pipeline.query("python question")
        assert "Hybrid result" in result.augmented_prompt
        assert len(result.sources) == 1
        assert result.sources[0].retrieval_method == "hybrid"
        # Should NOT have called the vector-only path.
        mock_embedder.embed.assert_not_called()
        mock_memory.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_hybrid_no_results(self) -> None:
        mock_embedder = AsyncMock()
        mock_memory = AsyncMock()
        mock_hybrid = AsyncMock()
        mock_hybrid.search.return_value = []

        pipeline = RAGPipeline(
            embedding_provider=mock_embedder,
            long_term_memory=mock_memory,
            hybrid_searcher=mock_hybrid,
        )
        result = await pipeline.query("obscure query")
        assert result.augmented_prompt == "obscure query"
        assert result.sources == []

    @pytest.mark.asyncio
    async def test_prompt_format(self) -> None:
        """Verify the augmented prompt structure."""
        mock_embedder = AsyncMock()
        mock_embedder.embed.return_value = [0.1] * 1536
        mock_memory = AsyncMock()
        mock_memory.search.return_value = [
            SearchResult(text="Source A", score=0.9, metadata={}),
            SearchResult(text="Source B", score=0.8, metadata={}),
        ]

        pipeline = RAGPipeline(
            embedding_provider=mock_embedder,
            long_term_memory=mock_memory,
        )
        result = await pipeline.query("my question")
        assert result.augmented_prompt.startswith("Use the following context")
        assert "[Source 1] Source A" in result.augmented_prompt
        assert "[Source 2] Source B" in result.augmented_prompt
        assert result.augmented_prompt.endswith("Question: my question")
        assert len(result.sources) == 2

    @pytest.mark.asyncio
    async def test_source_metadata_preserved(self) -> None:
        mock_embedder = AsyncMock()
        mock_embedder.embed.return_value = [0.1] * 1536
        mock_memory = AsyncMock()
        mock_memory.search.return_value = [
            SearchResult(
                text="Data",
                score=0.85,
                metadata={"session_id": "s1", "agent_name": "coder"},
            ),
        ]

        pipeline = RAGPipeline(
            embedding_provider=mock_embedder,
            long_term_memory=mock_memory,
        )
        result = await pipeline.query("test")
        assert result.sources[0].metadata["session_id"] == "s1"
        assert result.sources[0].metadata["agent_name"] == "coder"

    @pytest.mark.asyncio
    async def test_query_with_diagnostics_vector_pipeline(self) -> None:
        mock_embedder = AsyncMock()
        mock_embedder.embed.return_value = [0.2] * 1536
        mock_memory = AsyncMock()
        mock_memory.search.return_value = [
            SearchResult(text="Vector source", score=0.9, metadata={}),
        ]

        pipeline = RAGPipeline(
            embedding_provider=mock_embedder,
            long_term_memory=mock_memory,
            similarity_threshold=0.3,
        )
        outcome = await pipeline.query_with_diagnostics("vector question")
        assert outcome.result.sources[0].retrieval_method == "vector"
        assert outcome.diagnostics.retrieval_method == "vector"
        stage_names = [stage.stage for stage in outcome.diagnostics.stages]
        assert stage_names == [
            "vector-search",
            "threshold-filter",
            "source-map",
            "prompt-assembly",
        ]

    @pytest.mark.asyncio
    async def test_query_with_diagnostics_hybrid_pipeline(self) -> None:
        mock_embedder = AsyncMock()
        mock_memory = AsyncMock()
        mock_hybrid = AsyncMock()
        mock_hybrid.search.return_value = [
            HybridResult(text="Hybrid source", score=0.5, metadata={}),
        ]

        pipeline = RAGPipeline(
            embedding_provider=mock_embedder,
            long_term_memory=mock_memory,
            hybrid_searcher=mock_hybrid,
        )
        outcome = await pipeline.query_with_diagnostics("hybrid question")
        assert outcome.result.sources[0].retrieval_method == "hybrid"
        assert outcome.diagnostics.retrieval_method == "hybrid"
        stage_names = [stage.stage for stage in outcome.diagnostics.stages]
        assert stage_names == ["hybrid-search", "source-map", "prompt-assembly"]


# ═══════════════════════════════════════════════════════════════════════
# Config Tests
# ═══════════════════════════════════════════════════════════════════════


class TestHybridRAGConfig:
    """Test new config settings for hybrid search and chunking."""

    def test_defaults(self) -> None:
        from agent33.config import Settings

        s = Settings()
        assert s.embedding_cache_enabled is True
        assert s.embedding_cache_max_size == 1024
        assert s.rag_hybrid_enabled is True
        assert s.rag_vector_weight == 0.7
        assert s.rag_rrf_k == 60
        assert s.rag_top_k == 5
        assert s.rag_similarity_threshold == 0.3
        assert s.chunk_tokens == 1200
        assert s.chunk_overlap_tokens == 100
