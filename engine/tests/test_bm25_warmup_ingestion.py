"""Tests for BM25 warm-up, LongTermMemory.scan/count, ingestion endpoint,
and warm-up config settings.

Every test asserts on real behavior: paginated DB reads, warm-up page
iteration, chunking+embedding+storage pipeline, BM25 indexing, and
error handling for missing subsystems.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from agent33.memory.bm25 import BM25Index
from agent33.memory.long_term import LongTermMemory, SearchResult
from agent33.memory.warmup import warm_up_bm25

# =====================================================================
# LongTermMemory.scan() and count() tests
# =====================================================================


class TestLongTermMemoryScan:
    """Test the paginated scan method on LongTermMemory."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock async session factory for LongTermMemory."""
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        return session

    @pytest.fixture
    def ltm_with_session(self, mock_session):
        """Return (LongTermMemory, mock_session) with patched internals."""
        with patch.object(LongTermMemory, "__init__", lambda self, *a, **kw: None):
            ltm = LongTermMemory.__new__(LongTermMemory)
            ltm._session_factory = MagicMock(return_value=mock_session)
            ltm._engine = AsyncMock()
            ltm._embedding_dim = 1536
        return ltm, mock_session

    @pytest.mark.asyncio
    async def test_scan_returns_results(self, ltm_with_session):
        """scan() converts DB rows to SearchResult objects."""
        ltm, mock_session = ltm_with_session

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("content A", {"source": "test"}),
            ("content B", None),
            ("content C", {"key": "val"}),
        ]
        mock_session.execute = AsyncMock(return_value=mock_result)

        results = await ltm.scan(limit=10, offset=0)

        assert len(results) == 3
        assert results[0].text == "content A"
        assert results[0].score == 0.0
        assert results[0].metadata == {"source": "test"}
        # None metadata should become empty dict
        assert results[1].metadata == {}
        assert results[2].text == "content C"

    @pytest.mark.asyncio
    async def test_scan_empty_table(self, ltm_with_session):
        """scan() returns empty list when no records exist."""
        ltm, mock_session = ltm_with_session

        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        results = await ltm.scan(limit=100, offset=0)

        assert results == []

    @pytest.mark.asyncio
    async def test_scan_respects_limit_and_offset(self, ltm_with_session):
        """scan() passes limit and offset to the SQL query."""
        ltm, mock_session = ltm_with_session

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("text", {"m": 1})]
        mock_session.execute = AsyncMock(return_value=mock_result)

        await ltm.scan(limit=50, offset=200)

        # Verify the execute call included the correct params
        call_args = mock_session.execute.call_args
        params = call_args[0][1]  # second positional arg is the params dict
        assert params["limit"] == 50
        assert params["offset"] == 200

    @pytest.mark.asyncio
    async def test_count_returns_total(self, ltm_with_session):
        """count() returns the total number of records."""
        ltm, mock_session = ltm_with_session

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (42,)
        mock_session.execute = AsyncMock(return_value=mock_result)

        total = await ltm.count()

        assert total == 42

    @pytest.mark.asyncio
    async def test_count_empty_table(self, ltm_with_session):
        """count() returns 0 when no records exist."""
        ltm, mock_session = ltm_with_session

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (0,)
        mock_session.execute = AsyncMock(return_value=mock_result)

        total = await ltm.count()

        assert total == 0


# =====================================================================
# warm_up_bm25 tests
# =====================================================================


class TestWarmUpBM25:
    """Test the BM25 warm-up function that loads records into the index."""

    @pytest.mark.asyncio
    async def test_warmup_loads_records(self):
        """Warm-up iterates pages and adds all records to BM25."""
        mock_ltm = AsyncMock()
        # Two pages of results, then empty
        page1 = [
            SearchResult(text="document one about python", score=0.0, metadata={"id": 1}),
            SearchResult(text="document two about java", score=0.0, metadata={"id": 2}),
        ]
        page2 = [
            SearchResult(text="document three about rust", score=0.0, metadata={"id": 3}),
        ]
        mock_ltm.scan = AsyncMock(side_effect=[page1, page2, []])

        bm25 = BM25Index()
        loaded = await warm_up_bm25(mock_ltm, bm25, page_size=2, max_records=100)

        assert loaded == 3
        assert bm25.size == 3
        # Verify the documents are actually searchable
        results = bm25.search("python")
        assert len(results) == 1
        assert "python" in results[0].text

    @pytest.mark.asyncio
    async def test_warmup_empty_database(self):
        """Warm-up with no records returns 0 and leaves index empty."""
        mock_ltm = AsyncMock()
        mock_ltm.scan = AsyncMock(return_value=[])

        bm25 = BM25Index()
        loaded = await warm_up_bm25(mock_ltm, bm25, page_size=100)

        assert loaded == 0
        assert bm25.size == 0

    @pytest.mark.asyncio
    async def test_warmup_respects_max_records(self):
        """Warm-up stops loading after max_records is reached."""
        mock_ltm = AsyncMock()

        def make_page(limit, offset):
            """Generate a page of records up to the requested limit."""
            return [
                SearchResult(text=f"record {offset + i}", score=0.0, metadata={})
                for i in range(limit)
            ]

        mock_ltm.scan = AsyncMock(side_effect=lambda limit, offset: make_page(limit, offset))

        bm25 = BM25Index()
        loaded = await warm_up_bm25(mock_ltm, bm25, page_size=3, max_records=5)

        assert loaded == 5
        assert bm25.size == 5

    @pytest.mark.asyncio
    async def test_warmup_page_size(self):
        """Warm-up calls scan with the configured page_size."""
        mock_ltm = AsyncMock()
        mock_ltm.scan = AsyncMock(return_value=[])

        bm25 = BM25Index()
        await warm_up_bm25(mock_ltm, bm25, page_size=77, max_records=1000)

        # First call should use page_size=77
        call_args = mock_ltm.scan.call_args_list[0]
        assert call_args.kwargs.get("limit", call_args[1].get("limit")) == 77 or (
            call_args[0] == () and call_args[1]["limit"] == 77
        )

    @pytest.mark.asyncio
    async def test_warmup_preserves_metadata(self):
        """Warm-up passes metadata from records to the BM25 index."""
        mock_ltm = AsyncMock()
        mock_ltm.scan = AsyncMock(
            side_effect=[
                [
                    SearchResult(
                        text="test document content",
                        score=0.0,
                        metadata={"source": "wiki", "lang": "en"},
                    )
                ],
                [],
            ]
        )

        bm25 = BM25Index()
        await warm_up_bm25(mock_ltm, bm25, page_size=100)

        results = bm25.search("test document")
        assert len(results) == 1
        assert results[0].metadata == {"source": "wiki", "lang": "en"}


# =====================================================================
# Config tests
# =====================================================================


class TestBM25WarmupConfig:
    """Test BM25 warm-up config defaults."""

    def test_bm25_warmup_settings_defaults(self):
        """Settings class has BM25 warm-up fields with correct defaults."""
        from agent33.config import Settings

        s = Settings()
        assert s.bm25_warmup_enabled is True
        assert s.bm25_warmup_max_records == 10_000
        assert s.bm25_warmup_page_size == 200


# =====================================================================
# Ingest endpoint tests
# =====================================================================


class TestIngestEndpoint:
    """Test the /v1/memory/ingest endpoint."""

    @pytest.fixture
    def auth_token(self):
        from agent33.security.auth import create_access_token

        return create_access_token("test-user", scopes=["admin"])

    @pytest.fixture
    def mock_ltm(self):
        ltm = AsyncMock()
        # store() returns an incrementing record id
        ltm.store = AsyncMock(side_effect=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        return ltm

    @pytest.fixture
    def mock_embedder(self):
        embedder = AsyncMock()
        embedder.embed_batch = AsyncMock(side_effect=lambda texts: [[0.1] * 1536 for _ in texts])
        return embedder

    @pytest.fixture
    def mock_bm25(self):
        return BM25Index()

    @pytest.fixture
    def client(self, auth_token, mock_ltm, mock_embedder, mock_bm25):
        from agent33.main import app

        app.state.long_term_memory = mock_ltm
        app.state.embedding_cache = mock_embedder
        app.state.bm25_index = mock_bm25
        client = TestClient(app, headers={"Authorization": f"Bearer {auth_token}"})
        yield client
        # Cleanup
        if hasattr(app.state, "long_term_memory"):
            del app.state.long_term_memory
        if hasattr(app.state, "embedding_cache"):
            del app.state.embedding_cache
        if hasattr(app.state, "bm25_index"):
            del app.state.bm25_index

    def test_ingest_text_token_aware(self, client, mock_ltm, mock_embedder):
        """Ingest plain text with token_aware chunking stores chunks."""
        resp = client.post(
            "/v1/memory/ingest",
            json={
                "content": "This is test content. It has two sentences.",
                "content_type": "text/plain",
                "chunk_strategy": "token_aware",
                "chunk_size": 1200,
                "chunk_overlap": 100,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["chunks_created"] >= 1
        assert len(data["record_ids"]) == data["chunks_created"]
        assert data["bm25_indexed"] is True
        # Verify embedder and store were called
        mock_embedder.embed_batch.assert_called_once()
        assert mock_ltm.store.call_count == data["chunks_created"]

    def test_ingest_markdown_token_aware(self, client, mock_ltm):
        """Ingest markdown content with token_aware chunking."""
        md = "# Heading\n\nSome paragraph.\n\n# Another\n\nMore text."
        resp = client.post(
            "/v1/memory/ingest",
            json={
                "content": md,
                "content_type": "text/markdown",
                "chunk_strategy": "token_aware",
                "chunk_size": 1200,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["chunks_created"] >= 1
        assert data["bm25_indexed"] is True

    def test_ingest_character_strategy(self, client, mock_ltm):
        """Ingest using the legacy character-based chunking strategy."""
        content = "A" * 1200
        resp = client.post(
            "/v1/memory/ingest",
            json={
                "content": content,
                "content_type": "text/plain",
                "chunk_strategy": "character",
                "chunk_size": 500,
                "chunk_overlap": 50,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["chunks_created"] >= 2  # 1200 chars, 500 per chunk
        assert data["bm25_indexed"] is True

    def test_ingest_empty_content(self, client):
        """Ingesting empty content returns 0 chunks."""
        resp = client.post(
            "/v1/memory/ingest",
            json={"content": "", "chunk_strategy": "token_aware"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["chunks_created"] == 0
        assert data["record_ids"] == []
        assert data["bm25_indexed"] is False

    def test_ingest_adds_to_bm25(self, client, mock_bm25):
        """Ingested content is added to the BM25 index."""
        resp = client.post(
            "/v1/memory/ingest",
            json={
                "content": "Python programming language tutorial.",
                "chunk_strategy": "token_aware",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["bm25_indexed"] is True
        # Verify BM25 index now has the content
        assert mock_bm25.size >= 1
        results = mock_bm25.search("python")
        assert len(results) >= 1

    def test_ingest_no_bm25_index(self, auth_token, mock_ltm, mock_embedder):
        """Ingestion works without BM25, bm25_indexed=False."""
        from agent33.main import app

        app.state.long_term_memory = mock_ltm
        app.state.embedding_cache = mock_embedder
        # Explicitly remove bm25_index
        if hasattr(app.state, "bm25_index"):
            del app.state.bm25_index

        client = TestClient(app, headers={"Authorization": f"Bearer {auth_token}"})
        try:
            resp = client.post(
                "/v1/memory/ingest",
                json={
                    "content": "Some content here.",
                    "chunk_strategy": "token_aware",
                },
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["chunks_created"] >= 1
            assert data["bm25_indexed"] is False
        finally:
            if hasattr(app.state, "long_term_memory"):
                del app.state.long_term_memory
            if hasattr(app.state, "embedding_cache"):
                del app.state.embedding_cache

    def test_ingest_no_memory_system(self, auth_token):
        """Returns 503 when long_term_memory is not initialized."""
        from agent33.main import app

        # Ensure long_term_memory is not set
        ltm_backup = getattr(app.state, "long_term_memory", None)
        if hasattr(app.state, "long_term_memory"):
            del app.state.long_term_memory

        client = TestClient(app, headers={"Authorization": f"Bearer {auth_token}"})
        try:
            resp = client.post(
                "/v1/memory/ingest",
                json={"content": "test"},
            )
            assert resp.status_code == 503
            assert "Memory system" in resp.json()["detail"]
        finally:
            if ltm_backup is not None:
                app.state.long_term_memory = ltm_backup

    def test_ingest_no_embedding_provider(self, auth_token, mock_ltm):
        """Returns 503 when embedding provider is not initialized."""
        from agent33.main import app

        app.state.long_term_memory = mock_ltm
        # Ensure no embedder is set
        cache_backup = getattr(app.state, "embedding_cache", None)
        provider_backup = getattr(app.state, "embedding_provider", None)
        if hasattr(app.state, "embedding_cache"):
            del app.state.embedding_cache
        if hasattr(app.state, "embedding_provider"):
            del app.state.embedding_provider

        client = TestClient(app, headers={"Authorization": f"Bearer {auth_token}"})
        try:
            resp = client.post(
                "/v1/memory/ingest",
                json={"content": "test"},
            )
            assert resp.status_code == 503
            assert "Embedding provider" in resp.json()["detail"]
        finally:
            if hasattr(app.state, "long_term_memory"):
                del app.state.long_term_memory
            if cache_backup is not None:
                app.state.embedding_cache = cache_backup
            if provider_backup is not None:
                app.state.embedding_provider = provider_backup

    def test_ingest_metadata_forwarded(self, client, mock_ltm, mock_embedder):
        """Request metadata is merged with chunk metadata in storage."""
        resp = client.post(
            "/v1/memory/ingest",
            json={
                "content": "Some important content.",
                "metadata": {"project": "agent33", "lang": "en"},
                "chunk_strategy": "token_aware",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["chunks_created"] >= 1

        # Verify the store call received merged metadata
        store_call = mock_ltm.store.call_args_list[0]
        stored_meta = store_call[0][2] if len(store_call[0]) > 2 else store_call[1].get("metadata")
        # If positional: store(text, embedding, meta)
        # The metadata should include both request metadata and chunk metadata
        assert "project" in stored_meta
        assert stored_meta["project"] == "agent33"
        assert stored_meta["lang"] == "en"

    def test_ingest_markdown_character_strategy(self, client, mock_ltm):
        """Ingest markdown with character-based chunking."""
        md = "# Title\n\nA paragraph. " + "B " * 300
        resp = client.post(
            "/v1/memory/ingest",
            json={
                "content": md,
                "content_type": "text/markdown",
                "chunk_strategy": "character",
                "chunk_size": 200,
                "chunk_overlap": 20,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["chunks_created"] >= 1
        assert data["bm25_indexed"] is True
