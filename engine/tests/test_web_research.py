"""Comprehensive tests for the web research service (Track 7)."""

from __future__ import annotations

import contextlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio

from agent33.main import app
from agent33.security.auth import create_access_token
from agent33.web_research.models import (
    ProviderAuthState,
    ResearchFetchRequest,
    ResearchProviderKind,
    ResearchProviderStatus,
    ResearchSearchRequest,
    ResearchSearchResponse,
    ResearchTrustLevel,
    WebFetchArtifact,
    WebResearchCitation,
    WebResearchResult,
)
from agent33.web_research.service import (
    GovernedFetchProvider,
    SearXNGSearchProvider,
    WebResearchService,
    create_default_web_research_service,
)

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _auth_headers(*, scopes: list[str] | None = None) -> dict[str, str]:
    token = create_access_token(
        "research-user",
        scopes=scopes or [],
        tenant_id="tenant-a",
    )
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestModels:
    """Test model construction, serialization, and enum values."""

    def test_research_trust_level_enum_values(self) -> None:
        assert ResearchTrustLevel.SEARCH_INDEXED == "search-indexed"
        assert ResearchTrustLevel.FETCH_VERIFIED == "fetch-verified"
        assert ResearchTrustLevel.BLOCKED == "blocked"
        assert len(ResearchTrustLevel) == 3

    def test_research_provider_kind_enum_values(self) -> None:
        assert ResearchProviderKind.SEARCH == "search"
        assert ResearchProviderKind.FETCH == "fetch"
        assert len(ResearchProviderKind) == 2

    def test_provider_auth_state_enum_values(self) -> None:
        assert ProviderAuthState.NOT_REQUIRED == "not_required"
        assert ProviderAuthState.CONFIGURED == "configured"
        assert ProviderAuthState.MISSING == "missing"
        assert len(ProviderAuthState) == 3

    def test_web_research_citation_construction(self) -> None:
        citation = WebResearchCitation(
            title="Example Page",
            url="https://example.com/article",
            display_url="example.com/article",
            domain="example.com",
            provider_id="searxng",
            trust_level=ResearchTrustLevel.SEARCH_INDEXED,
            trust_reason="Indexed by searxng",
        )
        assert citation.title == "Example Page"
        assert citation.domain == "example.com"
        assert citation.trust_level == ResearchTrustLevel.SEARCH_INDEXED

    def test_web_research_citation_serialization_roundtrip(self) -> None:
        citation = WebResearchCitation(
            title="Test",
            url="https://test.dev",
            display_url="test.dev",
            domain="test.dev",
            provider_id="searxng",
            trust_level=ResearchTrustLevel.FETCH_VERIFIED,
            trust_reason="Fetched directly",
        )
        data = citation.model_dump()
        restored = WebResearchCitation.model_validate(data)
        assert restored.trust_level == ResearchTrustLevel.FETCH_VERIFIED
        assert restored.url == "https://test.dev"

    def test_web_research_result_construction(self) -> None:
        citation = WebResearchCitation(
            title="Result",
            url="https://result.io",
            display_url="result.io",
            domain="result.io",
            provider_id="searxng",
            trust_level=ResearchTrustLevel.SEARCH_INDEXED,
            trust_reason="Indexed",
        )
        result = WebResearchResult(
            title="Result",
            url="https://result.io",
            snippet="Some snippet text",
            provider_id="searxng",
            rank=3,
            domain="result.io",
            display_url="result.io",
            trust_level=ResearchTrustLevel.SEARCH_INDEXED,
            trust_reason="Indexed",
            citation=citation,
        )
        assert result.rank == 3
        assert result.snippet == "Some snippet text"
        assert result.citation.provider_id == "searxng"

    def test_web_fetch_artifact_construction(self) -> None:
        citation = WebResearchCitation(
            title="example.com/page",
            url="https://example.com/page",
            display_url="example.com/page",
            domain="example.com",
            provider_id="web_fetch",
            trust_level=ResearchTrustLevel.FETCH_VERIFIED,
            trust_reason="Fetched directly",
        )
        artifact = WebFetchArtifact(
            url="https://example.com/page",
            provider_id="web_fetch",
            status_code=200,
            content="<html>Hello</html>",
            content_preview="<html>Hello</html>",
            trust_level=ResearchTrustLevel.FETCH_VERIFIED,
            trust_reason="Fetched directly",
            citation=citation,
        )
        assert artifact.status_code == 200
        assert artifact.content == "<html>Hello</html>"
        assert artifact.trust_level == ResearchTrustLevel.FETCH_VERIFIED

    def test_provider_status_construction(self) -> None:
        status = ResearchProviderStatus(
            provider_id="searxng",
            display_name="SearXNG",
            kind=ResearchProviderKind.SEARCH,
            status="ok",
            auth_state=ProviderAuthState.NOT_REQUIRED,
            configured=True,
            capabilities=["search", "snippets"],
            is_default=True,
            detail="Base URL: http://localhost:8080",
        )
        assert status.provider_id == "searxng"
        assert status.kind == ResearchProviderKind.SEARCH
        assert status.is_default is True
        assert "search" in status.capabilities

    def test_research_search_request_validation(self) -> None:
        req = ResearchSearchRequest(query="test query", limit=5, categories="science")
        assert req.query == "test query"
        assert req.limit == 5
        assert req.categories == "science"
        assert req.provider is None

    def test_research_search_request_rejects_empty_query(self) -> None:
        with pytest.raises(Exception):  # noqa: B017
            ResearchSearchRequest(query="")

    def test_research_search_response_construction(self) -> None:
        response = ResearchSearchResponse(
            query="test",
            provider_id="searxng",
            results=[],
        )
        assert response.query == "test"
        assert response.provider_id == "searxng"
        assert response.results == []

    def test_research_fetch_request_defaults(self) -> None:
        req = ResearchFetchRequest(url="https://example.com")
        assert req.method == "GET"
        assert req.headers == {}
        assert req.body is None
        assert req.timeout == 30
        assert req.allowed_domains == []

    def test_research_fetch_request_custom_values(self) -> None:
        req = ResearchFetchRequest(
            url="https://api.example.com/data",
            method="POST",
            headers={"Content-Type": "application/json"},
            body='{"key": "value"}',
            timeout=60,
            allowed_domains=["example.com", "api.example.com"],
        )
        assert req.method == "POST"
        assert req.headers["Content-Type"] == "application/json"
        assert req.body == '{"key": "value"}'
        assert req.timeout == 60
        assert len(req.allowed_domains) == 2

    def test_research_fetch_request_rejects_empty_url(self) -> None:
        with pytest.raises(Exception):  # noqa: B017
            ResearchFetchRequest(url="")


# ---------------------------------------------------------------------------
# Provider tests
# ---------------------------------------------------------------------------


class TestSearXNGSearchProvider:
    """Tests for SearXNGSearchProvider diagnostics."""

    def test_diagnostics_when_url_configured(self) -> None:
        provider = SearXNGSearchProvider()
        with patch("agent33.web_research.service.settings") as mock_settings:
            mock_settings.searxng_url = "http://searxng:8080"
            diag = provider.diagnostics()
        assert diag.provider_id == "searxng"
        assert diag.display_name == "SearXNG"
        assert diag.kind == ResearchProviderKind.SEARCH
        assert diag.status == "ok"
        assert diag.configured is True
        # SearXNG is no longer the global default; DuckDuckGo is now the
        # zero-config fallback. The `is_default` flag is set by the registry.
        assert "search" in diag.capabilities
        assert "8080" in diag.detail

    def test_diagnostics_when_url_not_configured(self) -> None:
        provider = SearXNGSearchProvider()
        with patch("agent33.web_research.service.settings") as mock_settings:
            mock_settings.searxng_url = ""
            diag = provider.diagnostics()
        assert diag.status == "unconfigured"
        assert diag.configured is False
        assert "SEARXNG_URL" in diag.detail


class TestGovernedFetchProvider:
    """Tests for GovernedFetchProvider diagnostics and allowlist enforcement."""

    def test_diagnostics(self) -> None:
        provider = GovernedFetchProvider()
        diag = provider.diagnostics()
        assert diag.provider_id == "web_fetch"
        assert diag.display_name == "Governed HTTP Fetch"
        assert diag.kind == ResearchProviderKind.FETCH
        assert diag.status == "ok"
        assert diag.configured is True
        assert "allowlist-enforced" in diag.capabilities

    async def test_fetch_blocks_domain_not_in_allowlist(self) -> None:
        provider = GovernedFetchProvider()
        with pytest.raises(ValueError, match="not in the allowlist"):
            await provider.fetch(
                "https://evil.example.com/steal",
                headers={},
                body=None,
                method="GET",
                timeout=10,
                allowed_domains=["safe.example.com"],
            )

    async def test_fetch_blocks_empty_allowlist(self) -> None:
        provider = GovernedFetchProvider()
        with pytest.raises(ValueError, match="allowlist not configured"):
            await provider.fetch(
                "https://example.com/page",
                headers={},
                body=None,
                method="GET",
                timeout=10,
                allowed_domains=[],
            )

    async def test_fetch_allows_domain_in_allowlist(self) -> None:
        """Verify allowed domain passes the allowlist check and reaches HTTP."""
        provider = GovernedFetchProvider()
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.text = "<html>OK</html>"
        mock_response.content = b"<html>OK</html>"
        mock_response.raise_for_status = lambda: None

        with patch("agent33.web_research.service.build_connector_boundary_executor") as mock_bce:
            mock_bce.return_value = None
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client_inst = AsyncMock()
                mock_client_inst.get.return_value = mock_response
                mock_client_inst.__aenter__ = AsyncMock(return_value=mock_client_inst)
                mock_client_inst.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client_inst

                artifact = await provider.fetch(
                    "https://docs.example.com/api",
                    headers={},
                    body=None,
                    method="GET",
                    timeout=10,
                    allowed_domains=["example.com"],
                )

        assert artifact.url == "https://docs.example.com/api"
        assert artifact.status_code == 200
        assert artifact.content == "<html>OK</html>"
        assert artifact.trust_level == ResearchTrustLevel.FETCH_VERIFIED
        assert artifact.provider_id == "web_fetch"
        assert artifact.citation.domain == "docs.example.com"

    async def test_fetch_subdomain_matching(self) -> None:
        """Subdomain 'sub.example.com' should match allowlist entry 'example.com'."""
        provider = GovernedFetchProvider()
        # Should not raise for subdomain
        with pytest.raises(ValueError, match="not in the allowlist"):
            await provider.fetch(
                "https://other.io/page",
                headers={},
                body=None,
                method="GET",
                timeout=10,
                allowed_domains=["example.com"],
            )


# ---------------------------------------------------------------------------
# WebResearchService unit tests
# ---------------------------------------------------------------------------


class TestWebResearchService:
    """Unit tests for the unified research service."""

    def _make_service(
        self,
        *,
        search_results: list[WebResearchResult] | None = None,
        fetch_artifact: WebFetchArtifact | None = None,
    ) -> WebResearchService:
        """Build a service with mock providers for isolated testing."""
        mock_search = MagicMock()
        mock_search.provider_id = "mock-search"
        mock_search.diagnostics.return_value = ResearchProviderStatus(
            provider_id="mock-search",
            display_name="Mock Search",
            kind=ResearchProviderKind.SEARCH,
            status="ok",
            auth_state=ProviderAuthState.NOT_REQUIRED,
            configured=True,
            capabilities=["search"],
            is_default=True,
        )
        mock_search.search = AsyncMock(return_value=search_results or [])

        mock_fetch = MagicMock()
        mock_fetch.provider_id = "mock-fetch"
        mock_fetch.diagnostics.return_value = ResearchProviderStatus(
            provider_id="mock-fetch",
            display_name="Mock Fetch",
            kind=ResearchProviderKind.FETCH,
            status="ok",
            auth_state=ProviderAuthState.NOT_REQUIRED,
            configured=True,
            capabilities=["fetch"],
        )
        mock_fetch.fetch = AsyncMock(return_value=fetch_artifact)

        return WebResearchService(
            search_providers=[mock_search],
            fetch_providers=[mock_fetch],
            default_search_provider="mock-search",
            default_fetch_provider="mock-fetch",
        )

    def _sample_citation(self) -> WebResearchCitation:
        return WebResearchCitation(
            title="Test Result",
            url="https://test.dev/page",
            display_url="test.dev/page",
            domain="test.dev",
            provider_id="mock-search",
            trust_level=ResearchTrustLevel.SEARCH_INDEXED,
            trust_reason="Indexed by mock-search",
        )

    def _sample_result(self) -> WebResearchResult:
        citation = self._sample_citation()
        return WebResearchResult(
            title="Test Result",
            url="https://test.dev/page",
            snippet="A test snippet",
            provider_id="mock-search",
            rank=1,
            domain="test.dev",
            display_url="test.dev/page",
            trust_level=ResearchTrustLevel.SEARCH_INDEXED,
            trust_reason="Indexed by mock-search",
            citation=citation,
        )

    def _sample_artifact(self) -> WebFetchArtifact:
        return WebFetchArtifact(
            url="https://test.dev/page",
            provider_id="mock-fetch",
            status_code=200,
            content="<html>Test</html>",
            content_preview="<html>Test</html>",
            trust_level=ResearchTrustLevel.FETCH_VERIFIED,
            trust_reason="Fetched directly",
            citation=WebResearchCitation(
                title="test.dev/page",
                url="https://test.dev/page",
                display_url="test.dev/page",
                domain="test.dev",
                provider_id="mock-fetch",
                trust_level=ResearchTrustLevel.FETCH_VERIFIED,
                trust_reason="Fetched directly",
            ),
        )

    async def test_search_delegates_to_correct_provider(self) -> None:
        sample = self._sample_result()
        service = self._make_service(search_results=[sample])
        response = await service.search("test query", limit=5, categories="general")
        assert response.query == "test query"
        assert response.provider_id == "mock-search"
        assert len(response.results) == 1
        assert response.results[0].title == "Test Result"
        assert response.results[0].snippet == "A test snippet"
        assert response.results[0].trust_level == ResearchTrustLevel.SEARCH_INDEXED

    async def test_search_unknown_provider_raises_value_error(self) -> None:
        service = self._make_service()
        with pytest.raises(ValueError, match="Unknown research search provider"):
            await service.search("query", provider_id="nonexistent")

    async def test_search_uses_default_provider_when_none_specified(self) -> None:
        sample = self._sample_result()
        service = self._make_service(search_results=[sample])
        response = await service.search("default test")
        assert response.provider_id == "mock-search"

    async def test_fetch_delegates_to_correct_provider(self) -> None:
        artifact = self._sample_artifact()
        service = self._make_service(fetch_artifact=artifact)
        result = await service.fetch(
            "https://test.dev/page",
            allowed_domains=["test.dev"],
        )
        assert result.url == "https://test.dev/page"
        assert result.status_code == 200
        assert result.trust_level == ResearchTrustLevel.FETCH_VERIFIED
        assert result.content == "<html>Test</html>"

    async def test_fetch_unknown_provider_raises_value_error(self) -> None:
        service = self._make_service()
        with pytest.raises(ValueError, match="Unknown research fetch provider"):
            await service.fetch(
                "https://example.com",
                provider_id="nonexistent",
                allowed_domains=["example.com"],
            )

    async def test_fetch_uses_default_provider_when_none_specified(self) -> None:
        artifact = self._sample_artifact()
        service = self._make_service(fetch_artifact=artifact)
        result = await service.fetch(
            "https://test.dev/page",
            allowed_domains=["test.dev"],
        )
        assert result.provider_id == "mock-fetch"

    def test_list_providers_returns_all_diagnostics(self) -> None:
        service = self._make_service()
        providers = service.list_providers()
        assert len(providers) == 2
        ids = {p.provider_id for p in providers}
        assert "mock-search" in ids
        assert "mock-fetch" in ids
        kinds = {p.kind for p in providers}
        assert ResearchProviderKind.SEARCH in kinds
        assert ResearchProviderKind.FETCH in kinds

    def test_create_default_service_has_expected_providers(self) -> None:
        service = create_default_web_research_service()
        providers = service.list_providers()
        assert len(providers) == 2
        ids = {p.provider_id for p in providers}
        assert "searxng" in ids
        assert "web_fetch" in ids


# ---------------------------------------------------------------------------
# API route tests
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(autouse=True)
async def _install_web_research_service() -> Any:
    """Install a mock-backed research service on app.state."""
    mock_search_provider = MagicMock()
    mock_search_provider.provider_id = "searxng"
    mock_search_provider.diagnostics.return_value = ResearchProviderStatus(
        provider_id="searxng",
        display_name="SearXNG",
        kind=ResearchProviderKind.SEARCH,
        status="ok",
        auth_state=ProviderAuthState.NOT_REQUIRED,
        configured=True,
        capabilities=["search", "snippets"],
        is_default=True,
    )

    citation = WebResearchCitation(
        title="API Test Result",
        url="https://example.com/api-test",
        display_url="example.com/api-test",
        domain="example.com",
        provider_id="searxng",
        trust_level=ResearchTrustLevel.SEARCH_INDEXED,
        trust_reason="Indexed by searxng",
    )
    mock_search_provider.search = AsyncMock(
        return_value=[
            WebResearchResult(
                title="API Test Result",
                url="https://example.com/api-test",
                snippet="Result from mock search",
                provider_id="searxng",
                rank=1,
                domain="example.com",
                display_url="example.com/api-test",
                trust_level=ResearchTrustLevel.SEARCH_INDEXED,
                trust_reason="Indexed by searxng",
                citation=citation,
            ),
        ]
    )

    mock_fetch_provider = MagicMock()
    mock_fetch_provider.provider_id = "web_fetch"
    mock_fetch_provider.diagnostics.return_value = ResearchProviderStatus(
        provider_id="web_fetch",
        display_name="Governed HTTP Fetch",
        kind=ResearchProviderKind.FETCH,
        status="ok",
        auth_state=ProviderAuthState.NOT_REQUIRED,
        configured=True,
        capabilities=["fetch", "allowlist-enforced"],
    )
    fetch_citation = WebResearchCitation(
        title="example.com/page",
        url="https://example.com/page",
        display_url="example.com/page",
        domain="example.com",
        provider_id="web_fetch",
        trust_level=ResearchTrustLevel.FETCH_VERIFIED,
        trust_reason="Fetched directly by AGENT-33",
    )
    mock_fetch_provider.fetch = AsyncMock(
        return_value=WebFetchArtifact(
            url="https://example.com/page",
            provider_id="web_fetch",
            status_code=200,
            content="<html>Fetched content</html>",
            content_preview="<html>Fetched content</html>",
            trust_level=ResearchTrustLevel.FETCH_VERIFIED,
            trust_reason="Fetched directly by AGENT-33",
            citation=fetch_citation,
        )
    )

    service = WebResearchService(
        search_providers=[mock_search_provider],
        fetch_providers=[mock_fetch_provider],
        default_search_provider="searxng",
        default_fetch_provider="web_fetch",
    )

    original = getattr(app.state, "web_research_service", None)
    app.state.web_research_service = service
    # Also set via the module-level setter for the routes module
    from agent33.api.routes.research import set_research_service

    set_research_service(service)

    yield service

    set_research_service(None)
    if original is not None:
        app.state.web_research_service = original
    else:
        with contextlib.suppress(AttributeError):
            del app.state.web_research_service


@pytest_asyncio.fixture()
async def async_client() -> Any:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


class TestResearchRoutes:
    """API route tests for /v1/research/*."""

    async def test_list_providers_returns_provider_list(
        self, async_client: httpx.AsyncClient
    ) -> None:
        headers = _auth_headers(scopes=["tools:execute"])
        resp = await async_client.get("/v1/research/providers", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2
        ids = {p["provider_id"] for p in data}
        assert "searxng" in ids
        assert "web_fetch" in ids
        # Verify response shape for the search provider
        searxng_entry = next(p for p in data if p["provider_id"] == "searxng")
        assert searxng_entry["kind"] == "search"
        assert searxng_entry["configured"] is True
        assert "search" in searxng_entry["capabilities"]

    async def test_search_returns_structured_results(
        self, async_client: httpx.AsyncClient
    ) -> None:
        headers = _auth_headers(scopes=["tools:execute"])
        resp = await async_client.post(
            "/v1/research/search",
            json={"query": "test search", "limit": 5},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "test search"
        assert data["provider_id"] == "searxng"
        assert len(data["results"]) == 1
        result = data["results"][0]
        assert result["title"] == "API Test Result"
        assert result["url"] == "https://example.com/api-test"
        assert result["snippet"] == "Result from mock search"
        assert result["trust_level"] == "search-indexed"
        assert "citation" in result
        assert result["citation"]["domain"] == "example.com"

    async def test_fetch_returns_fetch_artifact(self, async_client: httpx.AsyncClient) -> None:
        headers = _auth_headers(scopes=["tools:execute"])
        resp = await async_client.post(
            "/v1/research/fetch",
            json={
                "url": "https://example.com/page",
                "allowed_domains": ["example.com"],
            },
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["url"] == "https://example.com/page"
        assert data["provider_id"] == "web_fetch"
        assert data["status_code"] == 200
        assert data["content"] == "<html>Fetched content</html>"
        assert data["trust_level"] == "fetch-verified"
        assert data["citation"]["domain"] == "example.com"

    async def test_search_with_unconfigured_provider_returns_503(
        self, async_client: httpx.AsyncClient
    ) -> None:
        """When a provider is requested that's not registered, return 400."""
        headers = _auth_headers(scopes=["tools:execute"])
        resp = await async_client.post(
            "/v1/research/search",
            json={"query": "test", "provider": "nonexistent"},
            headers=headers,
        )
        # The service raises ValueError("Unknown research search provider 'nonexistent'")
        # which the route maps to 400 (no "not configured" substring)
        assert resp.status_code == 400
        assert "Unknown" in resp.json()["detail"]

    async def test_search_unconfigured_searxng_returns_503(
        self,
        async_client: httpx.AsyncClient,
        _install_web_research_service: Any,
    ) -> None:
        """When SearXNG raises 'not configured', the route should return 503."""
        # Replace the mock to raise the specific error
        service = _install_web_research_service
        search_provider = list(service._search_providers.values())[0]
        search_provider.search.side_effect = ValueError("SearXNG provider is not configured")

        headers = _auth_headers(scopes=["tools:execute"])
        resp = await async_client.post(
            "/v1/research/search",
            json={"query": "test"},
            headers=headers,
        )
        assert resp.status_code == 503
        assert "not configured" in resp.json()["detail"]

    async def test_no_auth_returns_401(self, async_client: httpx.AsyncClient) -> None:
        providers_resp = await async_client.get("/v1/research/providers")
        search_resp = await async_client.post(
            "/v1/research/search",
            json={"query": "test"},
        )
        fetch_resp = await async_client.post(
            "/v1/research/fetch",
            json={"url": "https://example.com", "allowed_domains": ["example.com"]},
        )
        assert providers_resp.status_code == 401
        assert search_resp.status_code == 401
        assert fetch_resp.status_code == 401

    async def test_wrong_scope_returns_403(self, async_client: httpx.AsyncClient) -> None:
        headers = _auth_headers(scopes=["agents:read"])
        providers_resp = await async_client.get("/v1/research/providers", headers=headers)
        search_resp = await async_client.post(
            "/v1/research/search",
            json={"query": "test"},
            headers=headers,
        )
        fetch_resp = await async_client.post(
            "/v1/research/fetch",
            json={"url": "https://example.com", "allowed_domains": ["example.com"]},
            headers=headers,
        )
        assert providers_resp.status_code == 403
        assert search_resp.status_code == 403
        assert fetch_resp.status_code == 403

    async def test_fetch_error_propagates_as_400(
        self,
        async_client: httpx.AsyncClient,
        _install_web_research_service: Any,
    ) -> None:
        """When the fetch provider raises a ValueError, the route returns 400."""
        service = _install_web_research_service
        fetch_provider = list(service._fetch_providers.values())[0]
        fetch_provider.fetch.side_effect = ValueError("Domain 'evil.com' is not in the allowlist")

        headers = _auth_headers(scopes=["tools:execute"])
        resp = await async_client.post(
            "/v1/research/fetch",
            json={
                "url": "https://evil.com/steal",
                "allowed_domains": ["safe.com"],
            },
            headers=headers,
        )
        assert resp.status_code == 400
        assert "not in the allowlist" in resp.json()["detail"]

    async def test_search_validates_request_body(self, async_client: httpx.AsyncClient) -> None:
        """Empty query should fail validation (422)."""
        headers = _auth_headers(scopes=["tools:execute"])
        resp = await async_client.post(
            "/v1/research/search",
            json={"query": ""},
            headers=headers,
        )
        assert resp.status_code == 422

    async def test_fetch_validates_request_body(self, async_client: httpx.AsyncClient) -> None:
        """Empty URL should fail validation (422)."""
        headers = _auth_headers(scopes=["tools:execute"])
        resp = await async_client.post(
            "/v1/research/fetch",
            json={"url": ""},
            headers=headers,
        )
        assert resp.status_code == 422
