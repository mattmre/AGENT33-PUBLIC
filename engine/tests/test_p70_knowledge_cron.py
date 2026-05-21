"""Tests for P70: Knowledge Ingestion Cron.

Covers:
- Each ingestion adapter (RSS, GitHub, Web, LocalFolder) with mocked HTTP/filesystem
- Scheduler job add/remove and cron parsing
- Service orchestration: add/remove/list sources, manual ingest, staleness
- API routes with auth enforcement
- At least 20 behavioral tests
"""

from __future__ import annotations

import hashlib
import textwrap
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from agent33.knowledge.ingestion import (
    GitHubAdapter,
    LocalFolderAdapter,
    RSSAdapter,
    WebAdapter,
    _chunk_text,
    _strip_html,
)
from agent33.knowledge.models import KnowledgeSource, SourceType
from agent33.knowledge.scheduler import KnowledgeIngestionScheduler
from agent33.knowledge.service import KnowledgeIngestionService, _slugify

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth_headers(scopes: list[str] | None = None) -> dict[str, str]:
    """Create valid JWT auth headers with the given scopes."""
    from agent33.security.auth import create_access_token

    effective_scopes = (
        scopes
        if scopes is not None
        else [
            "admin",
            "agents:read",
            "agents:write",
            "agents:invoke",
        ]
    )
    token = create_access_token("test-user", scopes=effective_scopes, tenant_id="t-test")
    return {"Authorization": f"Bearer {token}"}


def _make_source(
    source_id: str = "test-src",
    name: str = "Test Source",
    source_type: SourceType = SourceType.RSS,
    url: str = "https://example.com/feed.xml",
    **kwargs: Any,
) -> KnowledgeSource:
    return KnowledgeSource(
        id=source_id,
        name=name,
        source_type=source_type,
        url=url,
        **kwargs,
    )


_SAMPLE_RSS = textwrap.dedent("""\
    <?xml version="1.0"?>
    <rss version="2.0">
      <channel>
        <title>Test Feed</title>
        <item>
          <title>Article One</title>
          <description>First article body.</description>
        </item>
        <item>
          <title>Article Two</title>
          <description>&lt;p&gt;Second &lt;b&gt;article&lt;/b&gt; body.&lt;/p&gt;</description>
        </item>
      </channel>
    </rss>
""")

_SAMPLE_ATOM = textwrap.dedent("""\
    <?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <title>Atom Feed</title>
      <entry>
        <title>Atom Entry</title>
        <summary>Atom summary text.</summary>
      </entry>
    </feed>
""")


# ---------------------------------------------------------------------------
# Utility tests
# ---------------------------------------------------------------------------


class TestUtilities:
    def test_strip_html_removes_tags(self) -> None:
        assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_strip_html_plain_text_passthrough(self) -> None:
        assert _strip_html("no tags here") == "no tags here"

    def test_chunk_text_splits_correctly(self) -> None:
        text = "a" * 3000
        chunks = _chunk_text(text, chunk_size=1200)
        assert len(chunks) == 3
        assert len(chunks[0]) == 1200
        assert len(chunks[1]) == 1200
        assert len(chunks[2]) == 600

    def test_chunk_text_empty_returns_empty(self) -> None:
        assert _chunk_text("") == []

    def test_slugify_produces_valid_slug(self) -> None:
        assert _slugify("My RSS Feed!") == "my-rss-feed"
        assert _slugify("CamelCase Test") == "camelcase-test"


# ---------------------------------------------------------------------------
# RSS Adapter
# ---------------------------------------------------------------------------


class TestRSSAdapter:
    async def test_rss_parses_items(self) -> None:
        source = _make_source(source_type=SourceType.RSS)
        mock_response = MagicMock()
        mock_response.text = _SAMPLE_RSS
        mock_response.raise_for_status = MagicMock()

        with patch("agent33.knowledge.ingestion.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            adapter = RSSAdapter()
            chunks = await adapter.fetch(source)

        assert len(chunks) == 2
        assert "Article One" in chunks[0]
        assert "First article body" in chunks[0]
        assert "Article Two" in chunks[1]

    async def test_rss_strips_html_in_description(self) -> None:
        source = _make_source(source_type=SourceType.RSS)
        mock_response = MagicMock()
        mock_response.text = _SAMPLE_RSS
        mock_response.raise_for_status = MagicMock()

        with patch("agent33.knowledge.ingestion.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            adapter = RSSAdapter()
            chunks = await adapter.fetch(source)

        # The second item has HTML entities in description
        assert "<p>" not in chunks[1]
        assert "<b>" not in chunks[1]

    async def test_rss_no_url_returns_empty(self) -> None:
        source = _make_source(url=None)
        adapter = RSSAdapter()
        chunks = await adapter.fetch(source)
        assert chunks == []

    async def test_atom_feed_parses_entries(self) -> None:
        source = _make_source(source_type=SourceType.RSS)
        mock_response = MagicMock()
        mock_response.text = _SAMPLE_ATOM
        mock_response.raise_for_status = MagicMock()

        with patch("agent33.knowledge.ingestion.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            adapter = RSSAdapter()
            chunks = await adapter.fetch(source)

        assert len(chunks) >= 1
        assert "Atom Entry" in chunks[0]


# ---------------------------------------------------------------------------
# GitHub Adapter
# ---------------------------------------------------------------------------


class TestGitHubAdapter:
    async def test_github_fetches_readme(self) -> None:
        import base64

        source = _make_source(
            source_type=SourceType.GITHUB,
            url="https://github.com/test/repo",
        )
        readme_content = base64.b64encode(b"# Test README\nHello world").decode()
        readme_response = MagicMock()
        readme_response.status_code = 200
        readme_response.json.return_value = {"content": readme_content}

        tree_response = MagicMock()
        tree_response.status_code = 200
        tree_response.json.return_value = {"tree": []}

        with patch("agent33.knowledge.ingestion.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=[readme_response, tree_response])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            adapter = GitHubAdapter()
            chunks = await adapter.fetch(source)

        assert len(chunks) == 1
        assert "Test README" in chunks[0]

    async def test_github_parses_owner_repo_from_url(self) -> None:
        adapter = GitHubAdapter()
        owner, repo = adapter._parse_owner_repo("https://github.com/octocat/hello-world")
        assert owner == "octocat"
        assert repo == "hello-world"

    async def test_github_parses_shorthand(self) -> None:
        adapter = GitHubAdapter()
        owner, repo = adapter._parse_owner_repo("octocat/hello-world")
        assert owner == "octocat"
        assert repo == "hello-world"

    async def test_github_no_url_returns_empty(self) -> None:
        source = _make_source(source_type=SourceType.GITHUB, url=None)
        adapter = GitHubAdapter()
        chunks = await adapter.fetch(source)
        assert chunks == []


# ---------------------------------------------------------------------------
# Web Adapter
# ---------------------------------------------------------------------------


class TestWebAdapter:
    async def test_web_strips_html_and_chunks(self) -> None:
        html = "<html><body><h1>Title</h1><p>" + "word " * 500 + "</p></body></html>"
        source = _make_source(source_type=SourceType.WEB, url="https://example.com/page")
        mock_response = MagicMock()
        mock_response.text = html
        mock_response.raise_for_status = MagicMock()

        with patch("agent33.knowledge.ingestion.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            adapter = WebAdapter()
            chunks = await adapter.fetch(source)

        assert len(chunks) >= 1
        # HTML tags should be stripped
        for chunk in chunks:
            assert "<html>" not in chunk
            assert "<body>" not in chunk

    async def test_web_no_url_returns_empty(self) -> None:
        source = _make_source(source_type=SourceType.WEB, url=None)
        adapter = WebAdapter()
        chunks = await adapter.fetch(source)
        assert chunks == []


# ---------------------------------------------------------------------------
# Local Folder Adapter
# ---------------------------------------------------------------------------


class TestLocalFolderAdapter:
    async def test_local_reads_txt_and_md_files(self, tmp_path: Path) -> None:
        (tmp_path / "doc.txt").write_text("Hello from text file", encoding="utf-8")
        (tmp_path / "notes.md").write_text("# Notes\nSome markdown", encoding="utf-8")
        (tmp_path / "image.png").write_bytes(b"\x89PNG")  # should be ignored

        source = _make_source(
            source_type=SourceType.LOCAL_FOLDER,
            url=None,
            local_path=str(tmp_path),
        )
        adapter = LocalFolderAdapter()
        chunks = await adapter.fetch(source)

        assert len(chunks) == 2
        texts = "\n".join(chunks)
        assert "Hello from text file" in texts
        assert "# Notes" in texts

    async def test_local_missing_folder_returns_empty(self) -> None:
        source = _make_source(
            source_type=SourceType.LOCAL_FOLDER,
            url=None,
            local_path="/nonexistent/path",
        )
        adapter = LocalFolderAdapter()
        chunks = await adapter.fetch(source)
        assert chunks == []

    async def test_local_no_path_returns_empty(self) -> None:
        source = _make_source(
            source_type=SourceType.LOCAL_FOLDER,
            url=None,
            local_path=None,
        )
        adapter = LocalFolderAdapter()
        chunks = await adapter.fetch(source)
        assert chunks == []

    async def test_local_chunks_large_files(self, tmp_path: Path) -> None:
        # Write a file larger than chunk size
        large_text = "a" * 3000
        (tmp_path / "large.txt").write_text(large_text, encoding="utf-8")

        source = _make_source(
            source_type=SourceType.LOCAL_FOLDER,
            url=None,
            local_path=str(tmp_path),
        )
        adapter = LocalFolderAdapter()
        chunks = await adapter.fetch(source)

        assert len(chunks) == 3  # 3000 / 1200 = 2.5 -> 3 chunks
        assert len(chunks[0]) == 1200
        assert len(chunks[2]) == 600


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


class TestKnowledgeIngestionScheduler:
    async def test_add_source_creates_job(self) -> None:
        callback = AsyncMock()
        scheduler = KnowledgeIngestionScheduler(on_ingest=callback)
        scheduler.start()
        try:
            scheduler.add_source("test-src", "0 */6 * * *")
            assert scheduler.has_job("test-src")
            assert "knowledge_test-src" in scheduler.list_jobs()
        finally:
            scheduler.stop()

    async def test_remove_source_removes_job(self) -> None:
        callback = AsyncMock()
        scheduler = KnowledgeIngestionScheduler(on_ingest=callback)
        scheduler.start()
        try:
            scheduler.add_source("test-src", "0 */6 * * *")
            assert scheduler.has_job("test-src")
            scheduler.remove_source("test-src")
            assert not scheduler.has_job("test-src")
        finally:
            scheduler.stop()

    def test_invalid_cron_expression_raises(self) -> None:
        callback = AsyncMock()
        scheduler = KnowledgeIngestionScheduler(on_ingest=callback)
        with pytest.raises(ValueError, match="5-field cron"):
            scheduler.add_source("bad", "* * *")

    async def test_idempotent_re_add(self) -> None:
        callback = AsyncMock()
        scheduler = KnowledgeIngestionScheduler(on_ingest=callback)
        scheduler.start()
        try:
            scheduler.add_source("src", "0 */6 * * *")
            scheduler.add_source("src", "0 */12 * * *")
            assert scheduler.has_job("src")
            jobs = scheduler.list_jobs()
            assert jobs.count("knowledge_src") == 1
        finally:
            scheduler.stop()


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class TestKnowledgeIngestionService:
    def test_add_source_returns_source_with_id(self) -> None:
        svc = KnowledgeIngestionService(
            long_term_memory=None,
            embedding_provider=None,
        )
        source = svc.add_source(name="My RSS", source_type="rss", url="https://example.com/rss")
        assert source.id == "my-rss"
        assert source.name == "My RSS"
        assert source.source_type == SourceType.RSS

    def test_add_source_deduplicates_ids(self) -> None:
        svc = KnowledgeIngestionService(
            long_term_memory=None,
            embedding_provider=None,
        )
        s1 = svc.add_source(name="My RSS", source_type="rss", url="https://a.com")
        s2 = svc.add_source(name="My RSS", source_type="rss", url="https://b.com")
        assert s1.id != s2.id
        assert s2.id == "my-rss-1"

    def test_remove_source_returns_true_for_existing(self) -> None:
        svc = KnowledgeIngestionService(
            long_term_memory=None,
            embedding_provider=None,
        )
        svc.add_source(name="src", source_type="rss", url="https://x.com")
        assert svc.remove_source("src") is True
        assert svc.remove_source("src") is False

    def test_list_sources_returns_all(self) -> None:
        svc = KnowledgeIngestionService(
            long_term_memory=None,
            embedding_provider=None,
        )
        svc.add_source(name="A", source_type="rss", url="https://a.com")
        svc.add_source(name="B", source_type="web", url="https://b.com")
        assert len(svc.list_sources()) == 2

    async def test_ingest_source_calls_adapter_and_stores(self) -> None:
        mock_ltm = AsyncMock()
        mock_ltm.store = AsyncMock(return_value=1)
        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])

        svc = KnowledgeIngestionService(
            long_term_memory=mock_ltm,
            embedding_provider=mock_embedder,
        )
        svc.add_source(name="Test", source_type="rss", url="https://example.com/rss")

        with patch("agent33.knowledge.service.get_adapter") as mock_get_adapter:
            mock_adapter = AsyncMock()
            mock_adapter.fetch = AsyncMock(return_value=["chunk one", "chunk two"])
            mock_get_adapter.return_value = mock_adapter

            result = await svc.ingest_source("test")

        assert result.status == "success"
        assert result.chunks_ingested == 2
        assert mock_ltm.store.call_count == 2
        assert mock_embedder.embed.call_count == 2

    async def test_ingest_source_skips_stale_content(self) -> None:
        mock_ltm = AsyncMock()
        mock_ltm.store = AsyncMock(return_value=1)
        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(return_value=[0.1])

        svc = KnowledgeIngestionService(
            long_term_memory=mock_ltm,
            embedding_provider=mock_embedder,
        )
        svc.add_source(name="Stale", source_type="rss", url="https://example.com/rss")

        chunks = ["chunk one", "chunk two"]
        raw = "\n".join(chunks)
        content_hash = hashlib.sha256(raw.encode()).hexdigest()

        # Pre-set the hash to simulate already-ingested content
        source = svc.get_source("stale")
        assert source is not None
        source.last_content_hash = content_hash

        with patch("agent33.knowledge.service.get_adapter") as mock_get_adapter:
            mock_adapter = AsyncMock()
            mock_adapter.fetch = AsyncMock(return_value=chunks)
            mock_get_adapter.return_value = mock_adapter

            result = await svc.ingest_source("stale")

        assert result.status == "skipped"
        assert result.chunks_ingested == 0
        # Store should NOT have been called
        mock_ltm.store.assert_not_called()

    async def test_ingest_unknown_source_returns_error(self) -> None:
        svc = KnowledgeIngestionService(
            long_term_memory=None,
            embedding_provider=None,
        )
        result = await svc.ingest_source("nonexistent")
        assert result.status == "error"
        assert "not found" in (result.error or "")

    async def test_ingest_empty_content_returns_skipped(self) -> None:
        svc = KnowledgeIngestionService(
            long_term_memory=None,
            embedding_provider=None,
        )
        svc.add_source(name="empty", source_type="rss", url="https://empty.com")

        with patch("agent33.knowledge.service.get_adapter") as mock_get_adapter:
            mock_adapter = AsyncMock()
            mock_adapter.fetch = AsyncMock(return_value=[])
            mock_get_adapter.return_value = mock_adapter

            result = await svc.ingest_source("empty")

        assert result.status == "skipped"

    async def test_ingest_updates_last_ingested_at(self) -> None:
        mock_ltm = AsyncMock()
        mock_ltm.store = AsyncMock(return_value=1)
        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(return_value=[0.5])

        svc = KnowledgeIngestionService(
            long_term_memory=mock_ltm,
            embedding_provider=mock_embedder,
        )
        svc.add_source(name="ts", source_type="rss", url="https://ts.com")

        before = datetime.now(UTC)
        with patch("agent33.knowledge.service.get_adapter") as mock_get_adapter:
            mock_adapter = AsyncMock()
            mock_adapter.fetch = AsyncMock(return_value=["content"])
            mock_get_adapter.return_value = mock_adapter

            result = await svc.ingest_source("ts")

        assert result.status == "success"
        source = svc.get_source("ts")
        assert source is not None
        assert source.last_ingested_at is not None
        assert source.last_ingested_at >= before
        assert source.last_content_hash is not None

    async def test_ingest_handles_adapter_error(self) -> None:
        svc = KnowledgeIngestionService(
            long_term_memory=None,
            embedding_provider=None,
        )
        svc.add_source(name="err", source_type="web", url="https://err.com")

        with patch("agent33.knowledge.service.get_adapter") as mock_get_adapter:
            mock_adapter = AsyncMock()
            mock_adapter.fetch = AsyncMock(side_effect=RuntimeError("network failure"))
            mock_get_adapter.return_value = mock_adapter

            result = await svc.ingest_source("err")

        assert result.status == "error"
        assert "network failure" in (result.error or "")

    async def test_get_last_result_returns_most_recent(self) -> None:
        svc = KnowledgeIngestionService(
            long_term_memory=None,
            embedding_provider=None,
        )
        svc.add_source(name="res", source_type="rss", url="https://res.com")

        with patch("agent33.knowledge.service.get_adapter") as mock_get_adapter:
            mock_adapter = AsyncMock()
            mock_adapter.fetch = AsyncMock(return_value=[])
            mock_get_adapter.return_value = mock_adapter

            await svc.ingest_source("res")

        last = svc.get_last_result("res")
        assert last is not None
        assert last.source_id == "res"


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------


class TestKnowledgeAPI:
    @pytest.fixture(autouse=True)
    def _install_service(self) -> Any:
        from agent33.main import app

        original = getattr(app.state, "knowledge_service", None)
        svc = KnowledgeIngestionService(
            long_term_memory=None,
            embedding_provider=None,
        )
        app.state.knowledge_service = svc
        yield svc
        if original is not None:
            app.state.knowledge_service = original
        elif hasattr(app.state, "knowledge_service"):
            del app.state.knowledge_service

    async def test_add_source_201(self, _install_service: Any) -> None:
        from agent33.main import app

        body = {
            "name": "Test RSS",
            "source_type": "rss",
            "url": "https://example.com/feed.xml",
        }
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/v1/knowledge/sources",
                json=body,
                headers=_auth_headers(),
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == "test-rss"
        assert data["name"] == "Test RSS"
        assert data["source_type"] == "rss"
        assert data["enabled"] is True

    async def test_list_sources_returns_all(self, _install_service: Any) -> None:
        from agent33.main import app

        svc: KnowledgeIngestionService = _install_service
        svc.add_source(name="A", source_type="rss", url="https://a.com")
        svc.add_source(name="B", source_type="web", url="https://b.com")

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get(
                "/v1/knowledge/sources",
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert len(data["sources"]) == 2

    async def test_delete_source_204(self, _install_service: Any) -> None:
        from agent33.main import app

        svc: KnowledgeIngestionService = _install_service
        svc.add_source(name="To Delete", source_type="rss", url="https://x.com")

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.delete(
                "/v1/knowledge/sources/to-delete",
                headers=_auth_headers(),
            )

        assert resp.status_code == 204

    async def test_delete_nonexistent_source_404(self, _install_service: Any) -> None:
        from agent33.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.delete(
                "/v1/knowledge/sources/ghost",
                headers=_auth_headers(),
            )

        assert resp.status_code == 404

    async def test_trigger_ingest_calls_service(self, _install_service: Any) -> None:
        from agent33.main import app

        svc: KnowledgeIngestionService = _install_service
        svc.add_source(name="Ingest Me", source_type="rss", url="https://i.com")

        with patch("agent33.knowledge.service.get_adapter") as mock_get_adapter:
            mock_adapter = AsyncMock()
            mock_adapter.fetch = AsyncMock(return_value=["chunk"])
            mock_get_adapter.return_value = mock_adapter

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.post(
                    "/v1/knowledge/sources/ingest-me/ingest",
                    headers=_auth_headers(),
                )

        assert resp.status_code == 200
        data = resp.json()
        # Without LTM, chunks_ingested will be 0 but status will be success
        # because the adapter returned content but store returned 0
        assert data["source_id"] == "ingest-me"
        assert data["status"] == "success"

    async def test_trigger_ingest_404_unknown(self, _install_service: Any) -> None:
        from agent33.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/v1/knowledge/sources/nope/ingest",
                headers=_auth_headers(),
            )

        assert resp.status_code == 404

    async def test_source_status_returns_source_and_result(
        self,
        _install_service: Any,
    ) -> None:
        from agent33.main import app

        svc: KnowledgeIngestionService = _install_service
        svc.add_source(name="Status", source_type="rss", url="https://s.com")

        # First, trigger an ingest so there's a result
        with patch("agent33.knowledge.service.get_adapter") as mock_get_adapter:
            mock_adapter = AsyncMock()
            mock_adapter.fetch = AsyncMock(return_value=[])
            mock_get_adapter.return_value = mock_adapter
            await svc.ingest_source("status")

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get(
                "/v1/knowledge/sources/status/status",
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["source"]["id"] == "status"
        assert data["last_result"] is not None
        assert data["last_result"]["source_id"] == "status"

    async def test_source_status_404_unknown(self, _install_service: Any) -> None:
        from agent33.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get(
                "/v1/knowledge/sources/ghost/status",
                headers=_auth_headers(),
            )

        assert resp.status_code == 404

    # -- Auth enforcement tests ----------------------------------------

    async def test_add_source_requires_auth(self) -> None:
        from agent33.main import app

        body = {"name": "No Auth", "source_type": "rss", "url": "https://x.com"}
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post("/v1/knowledge/sources", json=body)

        assert resp.status_code == 401

    async def test_list_sources_requires_auth(self) -> None:
        from agent33.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/v1/knowledge/sources")

        assert resp.status_code == 401

    async def test_delete_source_requires_auth(self) -> None:
        from agent33.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.delete("/v1/knowledge/sources/any")

        assert resp.status_code == 401

    async def test_trigger_ingest_requires_auth(self) -> None:
        from agent33.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post("/v1/knowledge/sources/any/ingest")

        assert resp.status_code == 401

    async def test_source_status_requires_auth(self) -> None:
        from agent33.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/v1/knowledge/sources/any/status")

        assert resp.status_code == 401
