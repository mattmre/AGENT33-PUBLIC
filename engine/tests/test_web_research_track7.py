"""Comprehensive tests for Track 7: Web Research Provider Abstraction and Trust.

Tests cover:
- TrustLabel enum and domain classification heuristics
- SearchProviderRegistry discovery and provider management
- DuckDuckGo HTML parsing (no API key required)
- Tavily/Brave provider diagnostics and configuration detection
- WebSearchTool (SchemaAwareTool protocol, multi-provider, trust labels)
- /v1/web-research/ API routes (providers, search, trust-domains, trust-classify)
- SearchResult model with trust_label, published_date, relevance_score fields
"""

from __future__ import annotations

import contextlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio

from agent33.main import app
from agent33.security.auth import create_access_token
from agent33.tools.base import ToolContext
from agent33.web_research.models import (
    ProviderAuthState,
    ResearchProviderKind,
    ResearchProviderStatus,
    ResearchTrustLevel,
    TrustedDomainEntry,
    TrustLabel,
    WebResearchCitation,
    WebResearchResult,
    classify_domain_trust,
)
from agent33.web_research.service import (
    BraveSearchProvider,
    DuckDuckGoSearchProvider,
    SearchProviderRegistry,
    TavilySearchProvider,
    _build_result,
    create_search_provider_registry,
)

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _auth_headers(*, scopes: list[str] | None = None) -> dict[str, str]:
    token = create_access_token(
        "t7-tester",
        scopes=scopes or [],
        tenant_id="tenant-t7",
    )
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# TrustLabel and domain classification tests
# ---------------------------------------------------------------------------


class TestTrustLabel:
    """Test TrustLabel enum values and domain classification heuristics."""

    def test_trust_label_enum_values(self) -> None:
        assert TrustLabel.VERIFIED == "verified"
        assert TrustLabel.COMMUNITY == "community"
        assert TrustLabel.UNKNOWN == "unknown"
        assert TrustLabel.SUSPICIOUS == "suspicious"
        assert len(TrustLabel) == 4

    def test_classify_verified_gov_domain(self) -> None:
        label, reason = classify_domain_trust("whitehouse.gov")
        assert label == TrustLabel.VERIFIED
        assert "authoritative" in reason.lower()

    def test_classify_verified_edu_domain(self) -> None:
        label, reason = classify_domain_trust("mit.edu")
        assert label == TrustLabel.VERIFIED
        assert "authoritative" in reason.lower()

    def test_classify_verified_wikipedia(self) -> None:
        label, reason = classify_domain_trust("en.wikipedia.org")
        assert label == TrustLabel.VERIFIED

    def test_classify_verified_gov_uk(self) -> None:
        label, reason = classify_domain_trust("service.gov.uk")
        assert label == TrustLabel.VERIFIED

    def test_classify_verified_academic_uk(self) -> None:
        label, reason = classify_domain_trust("oxford.ac.uk")
        assert label == TrustLabel.VERIFIED

    def test_classify_verified_docs_python(self) -> None:
        label, reason = classify_domain_trust("docs.python.org")
        assert label == TrustLabel.VERIFIED

    def test_classify_verified_mdn(self) -> None:
        label, reason = classify_domain_trust("developer.mozilla.org")
        assert label == TrustLabel.VERIFIED

    def test_classify_verified_arxiv(self) -> None:
        label, reason = classify_domain_trust("arxiv.org")
        assert label == TrustLabel.VERIFIED

    def test_classify_verified_reuters(self) -> None:
        label, reason = classify_domain_trust("reuters.com")
        assert label == TrustLabel.VERIFIED

    def test_classify_verified_bbc(self) -> None:
        label, reason = classify_domain_trust("bbc.co.uk")
        assert label == TrustLabel.VERIFIED

    def test_classify_verified_w3(self) -> None:
        label, reason = classify_domain_trust("w3.org")
        assert label == TrustLabel.VERIFIED

    def test_classify_community_stackoverflow(self) -> None:
        label, reason = classify_domain_trust("stackoverflow.com")
        assert label == TrustLabel.COMMUNITY
        assert "community" in reason.lower()

    def test_classify_community_github(self) -> None:
        label, reason = classify_domain_trust("github.com")
        assert label == TrustLabel.COMMUNITY

    def test_classify_community_reddit(self) -> None:
        label, reason = classify_domain_trust("reddit.com")
        assert label == TrustLabel.COMMUNITY

    def test_classify_community_medium(self) -> None:
        label, reason = classify_domain_trust("medium.com")
        assert label == TrustLabel.COMMUNITY

    def test_classify_community_devto(self) -> None:
        label, reason = classify_domain_trust("dev.to")
        assert label == TrustLabel.COMMUNITY

    def test_classify_suspicious_xyz_tld(self) -> None:
        label, reason = classify_domain_trust("spamsite.xyz")
        assert label == TrustLabel.SUSPICIOUS
        assert "suspicious" in reason.lower()

    def test_classify_suspicious_tk_tld(self) -> None:
        label, reason = classify_domain_trust("freesite.tk")
        assert label == TrustLabel.SUSPICIOUS

    def test_classify_suspicious_ip_address(self) -> None:
        label, reason = classify_domain_trust("192.168.1.1")
        assert label == TrustLabel.SUSPICIOUS

    def test_classify_suspicious_long_subdomain(self) -> None:
        # 60-char subdomain = phishing-like
        long_sub = "a" * 60 + ".example.com"
        label, reason = classify_domain_trust(long_sub)
        assert label == TrustLabel.SUSPICIOUS

    def test_classify_unknown_regular_domain(self) -> None:
        label, reason = classify_domain_trust("myblog.com")
        assert label == TrustLabel.UNKNOWN
        assert "no established reputation" in reason.lower()

    def test_classify_empty_domain(self) -> None:
        label, reason = classify_domain_trust("")
        assert label == TrustLabel.UNKNOWN
        assert "no domain" in reason.lower()

    def test_classify_is_case_insensitive(self) -> None:
        label1, _ = classify_domain_trust("WIKIPEDIA.ORG")
        label2, _ = classify_domain_trust("wikipedia.org")
        assert label1 == label2 == TrustLabel.VERIFIED


class TestTrustedDomainEntry:
    """Test the TrustedDomainEntry model."""

    def test_construction(self) -> None:
        entry = TrustedDomainEntry(
            pattern=r"\.gov$",
            label=TrustLabel.VERIFIED,
            category="verified",
        )
        assert entry.label == TrustLabel.VERIFIED
        assert entry.category == "verified"
        assert ".gov" in entry.pattern


# ---------------------------------------------------------------------------
# SearchResult enrichment tests
# ---------------------------------------------------------------------------


class TestWebResearchResultEnrichment:
    """Test that WebResearchResult now includes trust_label fields."""

    def test_result_has_trust_label_fields(self) -> None:
        citation = WebResearchCitation(
            title="Test",
            url="https://docs.python.org/3/tutorial/",
            display_url="docs.python.org/3/tutorial",
            domain="docs.python.org",
            provider_id="test",
            trust_level=ResearchTrustLevel.SEARCH_INDEXED,
            trust_reason="Indexed",
        )
        result = WebResearchResult(
            title="Python Tutorial",
            url="https://docs.python.org/3/tutorial/",
            snippet="Official Python tutorial",
            provider_id="test",
            rank=1,
            domain="docs.python.org",
            display_url="docs.python.org/3/tutorial",
            trust_level=ResearchTrustLevel.SEARCH_INDEXED,
            trust_reason="Indexed",
            citation=citation,
            trust_label=TrustLabel.VERIFIED,
            trust_label_reason="Known authoritative source",
            published_date="2024-01-15",
            relevance_score=0.95,
        )
        assert result.trust_label == TrustLabel.VERIFIED
        assert result.trust_label_reason == "Known authoritative source"
        assert result.published_date == "2024-01-15"
        assert result.relevance_score == 0.95

    def test_result_defaults_for_new_fields(self) -> None:
        citation = WebResearchCitation(
            title="Test",
            url="https://example.com",
            display_url="example.com",
            domain="example.com",
            provider_id="test",
            trust_level=ResearchTrustLevel.SEARCH_INDEXED,
            trust_reason="Indexed",
        )
        result = WebResearchResult(
            title="Test",
            url="https://example.com",
            provider_id="test",
            trust_level=ResearchTrustLevel.SEARCH_INDEXED,
            trust_reason="Indexed",
            citation=citation,
        )
        # New fields have sensible defaults
        assert result.trust_label == TrustLabel.UNKNOWN
        assert result.trust_label_reason == ""
        assert result.published_date is None
        assert result.relevance_score == 0.0

    def test_build_result_applies_trust_labels(self) -> None:
        """The _build_result helper must apply domain-based trust labels."""
        result = _build_result(
            title="Python Docs",
            url="https://docs.python.org/3/library/",
            snippet="Standard library reference",
            provider_id="test",
            rank=1,
        )
        assert result.trust_label == TrustLabel.VERIFIED
        assert "authoritative" in result.trust_label_reason.lower()
        assert result.domain == "docs.python.org"

    def test_build_result_community_domain(self) -> None:
        result = _build_result(
            title="How to X",
            url="https://stackoverflow.com/questions/12345",
            snippet="Answer to X",
            provider_id="test",
            rank=1,
        )
        assert result.trust_label == TrustLabel.COMMUNITY

    def test_build_result_unknown_domain(self) -> None:
        result = _build_result(
            title="Blog Post",
            url="https://randomblog.com/post/123",
            snippet="Some content",
            provider_id="test",
            rank=1,
        )
        assert result.trust_label == TrustLabel.UNKNOWN

    def test_build_result_preserves_relevance_score(self) -> None:
        result = _build_result(
            title="Test",
            url="https://example.com",
            snippet="Test",
            provider_id="test",
            rank=1,
            relevance_score=0.87,
        )
        assert result.relevance_score == 0.87

    def test_build_result_preserves_published_date(self) -> None:
        result = _build_result(
            title="Test",
            url="https://example.com",
            snippet="Test",
            provider_id="test",
            rank=1,
            published_date="2025-06-01",
        )
        assert result.published_date == "2025-06-01"


# ---------------------------------------------------------------------------
# DuckDuckGo provider tests
# ---------------------------------------------------------------------------


class TestDuckDuckGoProvider:
    """Test DuckDuckGo search provider (free, no API key)."""

    def test_diagnostics_always_configured(self) -> None:
        provider = DuckDuckGoSearchProvider()
        diag = provider.diagnostics()
        assert diag.provider_id == "duckduckgo"
        assert diag.display_name == "DuckDuckGo"
        assert diag.configured is True
        assert diag.auth_state == ProviderAuthState.NOT_REQUIRED
        assert diag.status == "ok"
        assert "No API key required" in diag.detail

    def test_parse_html_results_extracts_links(self) -> None:
        """Verify the HTML parser extracts results from DuckDuckGo HTML."""
        provider = DuckDuckGoSearchProvider()
        html = """
        <div class="result">
            <a class="result__a" href="https://example.com/page1">Example Page 1</a>
            <a class="result__snippet">This is snippet for page 1</a>
        </div>
        <div class="result">
            <a class="result__a" href="https://docs.python.org/3/">Python Docs</a>
            <a class="result__snippet">Official Python documentation</a>
        </div>
        """
        results = provider._parse_html_results(html, limit=10)
        assert len(results) == 2
        assert results[0].title == "Example Page 1"
        assert results[0].url == "https://example.com/page1"
        assert results[0].snippet == "This is snippet for page 1"
        assert results[0].provider_id == "duckduckgo"
        assert results[0].rank == 1
        # Second result should get trust labels from docs.python.org
        assert results[1].trust_label == TrustLabel.VERIFIED

    def test_parse_html_results_handles_uddg_redirect(self) -> None:
        """DuckDuckGo wraps URLs in redirect; parser should extract actual URL."""
        provider = DuckDuckGoSearchProvider()
        html = """
        <div class="result">
            <a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.com%2Freal&rut=abc">
                Real Page
            </a>
            <a class="result__snippet">The real snippet</a>
        </div>
        """
        results = provider._parse_html_results(html, limit=10)
        assert len(results) == 1
        assert results[0].url == "https://example.com/real"
        assert results[0].title == "Real Page"

    def test_parse_html_results_respects_limit(self) -> None:
        provider = DuckDuckGoSearchProvider()
        html = ""
        for i in range(20):
            html += f"""
            <div class="result">
                <a class="result__a" href="https://example.com/page{i}">Page {i}</a>
                <a class="result__snippet">Snippet {i}</a>
            </div>
            """
        results = provider._parse_html_results(html, limit=3)
        assert len(results) == 3

    def test_parse_html_results_strips_html_tags(self) -> None:
        provider = DuckDuckGoSearchProvider()
        html = """
        <div class="result">
            <a class="result__a" href="https://example.com">
                <b>Bold</b> Title <i>Italic</i>
            </a>
            <a class="result__snippet"><b>Bold</b> snippet text</a>
        </div>
        """
        results = provider._parse_html_results(html, limit=10)
        assert len(results) == 1
        assert results[0].title == "Bold Title Italic"
        assert results[0].snippet == "Bold snippet text"

    def test_parse_html_results_empty_html(self) -> None:
        provider = DuckDuckGoSearchProvider()
        results = provider._parse_html_results("<html></html>", limit=10)
        assert results == []

    async def test_search_makes_http_request(self) -> None:
        """Verify DuckDuckGo provider makes a real HTTP GET to html.duckduckgo.com."""
        provider = DuckDuckGoSearchProvider()
        html_response = """
        <div class="result">
            <a class="result__a" href="https://example.com">Test Result</a>
            <a class="result__snippet">Test snippet</a>
        </div>
        """
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.text = html_response
        mock_response.raise_for_status = lambda: None

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client_inst = AsyncMock()
            mock_client_inst.get.return_value = mock_response
            mock_client_inst.__aenter__ = AsyncMock(return_value=mock_client_inst)
            mock_client_inst.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client_inst

            results = await provider.search("test query", limit=5, categories="general")

        assert len(results) == 1
        assert results[0].title == "Test Result"
        # Verify the URL called
        call_args = mock_client_inst.get.call_args
        assert "html.duckduckgo.com" in str(call_args)

    async def test_search_handles_connection_error(self) -> None:
        provider = DuckDuckGoSearchProvider()
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client_inst = AsyncMock()
            mock_client_inst.get.side_effect = httpx.ConnectError("Connection refused")
            mock_client_inst.__aenter__ = AsyncMock(return_value=mock_client_inst)
            mock_client_inst.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client_inst

            with pytest.raises(ValueError, match="Could not connect to DuckDuckGo"):
                await provider.search("test", limit=5, categories="general")

    async def test_search_handles_timeout(self) -> None:
        provider = DuckDuckGoSearchProvider()
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client_inst = AsyncMock()
            mock_client_inst.get.side_effect = httpx.ReadTimeout("Timeout")
            mock_client_inst.__aenter__ = AsyncMock(return_value=mock_client_inst)
            mock_client_inst.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client_inst

            with pytest.raises(ValueError, match="timed out"):
                await provider.search("test", limit=5, categories="general")


# ---------------------------------------------------------------------------
# Tavily provider tests
# ---------------------------------------------------------------------------


class TestTavilyProvider:
    """Test Tavily search provider diagnostics and configuration."""

    def test_diagnostics_when_api_key_set(self) -> None:
        provider = TavilySearchProvider()
        with patch("agent33.web_research.service.settings") as mock_settings:
            mock_settings.tavily_api_key = MagicMock()
            mock_settings.tavily_api_key.get_secret_value.return_value = "tvly-fake-key"
            diag = provider.diagnostics()
        assert diag.provider_id == "tavily"
        assert diag.display_name == "Tavily"
        assert diag.configured is True
        assert diag.auth_state == ProviderAuthState.CONFIGURED
        assert "ai_optimized" in diag.capabilities

    def test_diagnostics_when_api_key_missing(self) -> None:
        provider = TavilySearchProvider()
        with patch("agent33.web_research.service.settings") as mock_settings:
            mock_settings.tavily_api_key = MagicMock()
            mock_settings.tavily_api_key.get_secret_value.return_value = ""
            diag = provider.diagnostics()
        assert diag.configured is False
        assert diag.auth_state == ProviderAuthState.MISSING
        assert "TAVILY_API_KEY" in diag.detail

    async def test_search_raises_when_unconfigured(self) -> None:
        provider = TavilySearchProvider()
        with patch("agent33.web_research.service.settings") as mock_settings:
            mock_settings.tavily_api_key = MagicMock()
            mock_settings.tavily_api_key.get_secret_value.return_value = ""
            with pytest.raises(ValueError, match="not configured"):
                await provider.search("test", limit=5, categories="general")

    async def test_search_calls_tavily_api(self) -> None:
        """Verify Tavily provider makes a POST to api.tavily.com/search."""
        provider = TavilySearchProvider()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "title": "Tavily Result",
                    "url": "https://example.com/tavily",
                    "content": "Result from Tavily API",
                    "score": 0.92,
                    "published_date": "2025-03-15",
                },
            ],
        }
        mock_response.raise_for_status = lambda: None

        with patch("agent33.web_research.service.settings") as mock_settings:
            mock_settings.tavily_api_key = MagicMock()
            mock_settings.tavily_api_key.get_secret_value.return_value = "tvly-fake-key"

            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client_inst = AsyncMock()
                mock_client_inst.post.return_value = mock_response
                mock_client_inst.__aenter__ = AsyncMock(return_value=mock_client_inst)
                mock_client_inst.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client_inst

                results = await provider.search("test", limit=5, categories="general")

        assert len(results) == 1
        assert results[0].title == "Tavily Result"
        assert results[0].relevance_score == 0.92
        assert results[0].published_date == "2025-03-15"
        assert results[0].provider_id == "tavily"
        # Verify POST to correct URL
        call_args = mock_client_inst.post.call_args
        assert "api.tavily.com" in str(call_args)


# ---------------------------------------------------------------------------
# Brave provider tests
# ---------------------------------------------------------------------------


class TestBraveProvider:
    """Test Brave Search provider diagnostics and configuration."""

    def test_diagnostics_when_api_key_set(self) -> None:
        provider = BraveSearchProvider()
        with patch("agent33.web_research.service.settings") as mock_settings:
            mock_settings.brave_api_key = MagicMock()
            mock_settings.brave_api_key.get_secret_value.return_value = "BSA-fake-key"
            diag = provider.diagnostics()
        assert diag.provider_id == "brave"
        assert diag.display_name == "Brave Search"
        assert diag.configured is True
        assert diag.auth_state == ProviderAuthState.CONFIGURED

    def test_diagnostics_when_api_key_missing(self) -> None:
        provider = BraveSearchProvider()
        with patch("agent33.web_research.service.settings") as mock_settings:
            mock_settings.brave_api_key = MagicMock()
            mock_settings.brave_api_key.get_secret_value.return_value = ""
            diag = provider.diagnostics()
        assert diag.configured is False
        assert "BRAVE_API_KEY" in diag.detail

    async def test_search_raises_when_unconfigured(self) -> None:
        provider = BraveSearchProvider()
        with patch("agent33.web_research.service.settings") as mock_settings:
            mock_settings.brave_api_key = MagicMock()
            mock_settings.brave_api_key.get_secret_value.return_value = ""
            with pytest.raises(ValueError, match="not configured"):
                await provider.search("test", limit=5, categories="general")

    async def test_search_calls_brave_api(self) -> None:
        """Verify Brave provider makes GET to api.search.brave.com."""
        provider = BraveSearchProvider()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "web": {
                "results": [
                    {
                        "title": "Brave Result",
                        "url": "https://example.com/brave",
                        "description": "Result from Brave Search",
                        "page_age": "2025-02-20",
                    },
                ],
            },
        }
        mock_response.raise_for_status = lambda: None

        with patch("agent33.web_research.service.settings") as mock_settings:
            mock_settings.brave_api_key = MagicMock()
            mock_settings.brave_api_key.get_secret_value.return_value = "BSA-key"

            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client_inst = AsyncMock()
                mock_client_inst.get.return_value = mock_response
                mock_client_inst.__aenter__ = AsyncMock(return_value=mock_client_inst)
                mock_client_inst.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client_inst

                results = await provider.search("test", limit=5, categories="general")

        assert len(results) == 1
        assert results[0].title == "Brave Result"
        assert results[0].published_date == "2025-02-20"
        assert results[0].provider_id == "brave"
        # Verify GET with API key header
        call_args = mock_client_inst.get.call_args
        assert "api.search.brave.com" in str(call_args)


# ---------------------------------------------------------------------------
# SearchProviderRegistry tests
# ---------------------------------------------------------------------------


class TestSearchProviderRegistry:
    """Test the provider registry auto-discovery and management."""

    def test_duckduckgo_always_registered(self) -> None:
        """DuckDuckGo must be available even without any API keys."""
        with patch("agent33.web_research.service.settings") as mock_settings:
            mock_settings.searxng_url = ""
            mock_settings.tavily_api_key = MagicMock()
            mock_settings.tavily_api_key.get_secret_value.return_value = ""
            mock_settings.brave_api_key = MagicMock()
            mock_settings.brave_api_key.get_secret_value.return_value = ""
            mock_settings.web_search_default_provider = None
            registry = create_search_provider_registry()

        assert "duckduckgo" in registry.list_provider_ids()
        assert registry.default_provider_id == "duckduckgo"

    def test_tavily_registered_when_key_set(self) -> None:
        with patch("agent33.web_research.service.settings") as mock_settings:
            mock_settings.searxng_url = ""
            mock_settings.tavily_api_key = MagicMock()
            mock_settings.tavily_api_key.get_secret_value.return_value = "tvly-key"
            mock_settings.brave_api_key = MagicMock()
            mock_settings.brave_api_key.get_secret_value.return_value = ""
            mock_settings.web_search_default_provider = None
            registry = create_search_provider_registry()

        assert "tavily" in registry.list_provider_ids()
        assert "duckduckgo" in registry.list_provider_ids()
        # Tavily should be default when configured
        assert registry.default_provider_id == "tavily"

    def test_brave_registered_when_key_set(self) -> None:
        with patch("agent33.web_research.service.settings") as mock_settings:
            mock_settings.searxng_url = ""
            mock_settings.tavily_api_key = MagicMock()
            mock_settings.tavily_api_key.get_secret_value.return_value = ""
            mock_settings.brave_api_key = MagicMock()
            mock_settings.brave_api_key.get_secret_value.return_value = "BSA-key"
            mock_settings.web_search_default_provider = None
            registry = create_search_provider_registry()

        assert "brave" in registry.list_provider_ids()
        assert registry.default_provider_id == "brave"

    def test_searxng_registered_when_url_set(self) -> None:
        with patch("agent33.web_research.service.settings") as mock_settings:
            mock_settings.searxng_url = "http://searxng:8080"
            mock_settings.tavily_api_key = MagicMock()
            mock_settings.tavily_api_key.get_secret_value.return_value = ""
            mock_settings.brave_api_key = MagicMock()
            mock_settings.brave_api_key.get_secret_value.return_value = ""
            mock_settings.web_search_default_provider = None
            registry = create_search_provider_registry()

        assert "searxng" in registry.list_provider_ids()
        assert registry.default_provider_id == "searxng"

    def test_all_providers_registered(self) -> None:
        with patch("agent33.web_research.service.settings") as mock_settings:
            mock_settings.searxng_url = "http://searxng:8080"
            mock_settings.tavily_api_key = MagicMock()
            mock_settings.tavily_api_key.get_secret_value.return_value = "tvly-key"
            mock_settings.brave_api_key = MagicMock()
            mock_settings.brave_api_key.get_secret_value.return_value = "BSA-key"
            mock_settings.web_search_default_provider = None
            registry = create_search_provider_registry()

        ids = set(registry.list_provider_ids())
        assert ids == {"duckduckgo", "searxng", "tavily", "brave"}
        # Tavily should be default (highest quality)
        assert registry.default_provider_id == "tavily"

    def test_explicit_default_provider_override(self) -> None:
        with patch("agent33.web_research.service.settings") as mock_settings:
            mock_settings.searxng_url = "http://searxng:8080"
            mock_settings.tavily_api_key = MagicMock()
            mock_settings.tavily_api_key.get_secret_value.return_value = "tvly-key"
            mock_settings.brave_api_key = MagicMock()
            mock_settings.brave_api_key.get_secret_value.return_value = ""
            mock_settings.web_search_default_provider = "searxng"
            registry = create_search_provider_registry()

        assert registry.default_provider_id == "searxng"

    def test_get_returns_provider_by_id(self) -> None:
        registry = SearchProviderRegistry()
        provider = DuckDuckGoSearchProvider()
        registry.register(provider)
        assert registry.get("duckduckgo") is provider
        assert registry.get("nonexistent") is None

    def test_list_diagnostics(self) -> None:
        registry = SearchProviderRegistry()
        registry.register(DuckDuckGoSearchProvider())
        diagnostics = registry.list_diagnostics()
        assert len(diagnostics) == 1
        assert diagnostics[0].provider_id == "duckduckgo"
        assert diagnostics[0].is_default is True  # DDG is default

    async def test_search_delegates_to_provider(self) -> None:
        registry = SearchProviderRegistry()
        mock_provider = MagicMock()
        mock_provider.provider_id = "mock"
        mock_provider.diagnostics.return_value = ResearchProviderStatus(
            provider_id="mock",
            display_name="Mock",
            kind=ResearchProviderKind.SEARCH,
            status="ok",
            auth_state=ProviderAuthState.NOT_REQUIRED,
            configured=True,
        )
        mock_provider.search = AsyncMock(return_value=[])
        registry.register(mock_provider)
        registry.set_default("mock")

        results = await registry.search("test query", limit=5)
        mock_provider.search.assert_called_once_with("test query", limit=5, categories="general")
        assert results == []

    async def test_search_unknown_provider_raises(self) -> None:
        registry = SearchProviderRegistry()
        registry.register(DuckDuckGoSearchProvider())
        with pytest.raises(ValueError, match="Unknown search provider"):
            await registry.search("test", provider_id="nonexistent")

    async def test_search_all_aggregates_and_deduplicates(self) -> None:
        registry = SearchProviderRegistry()

        # Create two mock providers that return overlapping results
        citation = WebResearchCitation(
            title="Shared",
            url="https://example.com/shared",
            display_url="example.com/shared",
            domain="example.com",
            provider_id="p1",
            trust_level=ResearchTrustLevel.SEARCH_INDEXED,
            trust_reason="Indexed",
        )
        shared_result = WebResearchResult(
            title="Shared",
            url="https://example.com/shared",
            snippet="Shared snippet",
            provider_id="p1",
            rank=1,
            trust_level=ResearchTrustLevel.SEARCH_INDEXED,
            trust_reason="Indexed",
            citation=citation,
        )
        unique_result = WebResearchResult(
            title="Unique",
            url="https://unique.com/page",
            snippet="Unique snippet",
            provider_id="p2",
            rank=1,
            trust_level=ResearchTrustLevel.SEARCH_INDEXED,
            trust_reason="Indexed",
            citation=citation.model_copy(
                update={"url": "https://unique.com/page", "provider_id": "p2"}
            ),
        )

        mock_p1 = MagicMock()
        mock_p1.provider_id = "p1"
        mock_p1.diagnostics.return_value = ResearchProviderStatus(
            provider_id="p1",
            display_name="P1",
            kind=ResearchProviderKind.SEARCH,
            status="ok",
            auth_state=ProviderAuthState.NOT_REQUIRED,
            configured=True,
        )
        mock_p1.search = AsyncMock(return_value=[shared_result])

        mock_p2 = MagicMock()
        mock_p2.provider_id = "p2"
        mock_p2.diagnostics.return_value = ResearchProviderStatus(
            provider_id="p2",
            display_name="P2",
            kind=ResearchProviderKind.SEARCH,
            status="ok",
            auth_state=ProviderAuthState.NOT_REQUIRED,
            configured=True,
        )
        # P2 returns the same URL (shared) plus a unique one
        shared_dup = shared_result.model_copy(update={"provider_id": "p2"})
        mock_p2.search = AsyncMock(return_value=[shared_dup, unique_result])

        registry.register(mock_p1)
        registry.register(mock_p2)

        results = await registry.search_all("test", limit=10)
        urls = [r.url for r in results]
        # Shared URL should appear only once (from p1, first provider)
        assert urls.count("https://example.com/shared") == 1
        assert "https://unique.com/page" in urls
        assert len(results) == 2

    async def test_search_all_skips_failed_providers(self) -> None:
        registry = SearchProviderRegistry()

        mock_ok = MagicMock()
        mock_ok.provider_id = "ok"
        mock_ok.diagnostics.return_value = ResearchProviderStatus(
            provider_id="ok",
            display_name="OK",
            kind=ResearchProviderKind.SEARCH,
            status="ok",
            auth_state=ProviderAuthState.NOT_REQUIRED,
            configured=True,
        )
        mock_ok.search = AsyncMock(return_value=[])

        mock_fail = MagicMock()
        mock_fail.provider_id = "fail"
        mock_fail.diagnostics.return_value = ResearchProviderStatus(
            provider_id="fail",
            display_name="Fail",
            kind=ResearchProviderKind.SEARCH,
            status="ok",
            auth_state=ProviderAuthState.NOT_REQUIRED,
            configured=True,
        )
        mock_fail.search = AsyncMock(side_effect=ValueError("Provider error"))

        registry.register(mock_ok)
        registry.register(mock_fail)

        # Should not raise; failed provider is skipped
        results = await registry.search_all("test", limit=5)
        assert isinstance(results, list)

    def test_get_trust_domain_entries(self) -> None:
        registry = SearchProviderRegistry()
        entries = registry.get_trust_domain_entries()
        assert len(entries) > 0
        labels = {e.label for e in entries}
        assert TrustLabel.VERIFIED in labels
        assert TrustLabel.COMMUNITY in labels
        assert TrustLabel.SUSPICIOUS in labels
        # All entries should have pattern and category
        for entry in entries:
            assert entry.pattern
            assert entry.category


# ---------------------------------------------------------------------------
# WebSearchTool tests
# ---------------------------------------------------------------------------


class TestWebSearchTool:
    """Test the SearchTool (SchemaAwareTool protocol)."""

    def test_schema_aware_properties(self) -> None:
        from agent33.tools.builtin.search import SearchTool

        tool = SearchTool()
        assert tool.name == "web_search"
        assert "search" in tool.description.lower()
        schema = tool.parameters_schema
        assert schema["type"] == "object"
        assert "query" in schema["properties"]
        assert "num_results" in schema["properties"]
        assert "provider" in schema["properties"]
        assert "all_providers" in schema["properties"]
        assert "query" in schema["required"]

    async def test_empty_query_returns_fail(self) -> None:
        from agent33.tools.builtin.search import SearchTool

        tool = SearchTool()
        context = ToolContext()
        result = await tool.execute({"query": ""}, context)
        assert not result.success
        assert "No search query" in result.error

    async def test_search_with_registry(self) -> None:
        from agent33.tools.builtin.search import SearchTool

        registry = SearchProviderRegistry()
        mock_provider = MagicMock()
        mock_provider.provider_id = "mock"
        mock_provider.diagnostics.return_value = ResearchProviderStatus(
            provider_id="mock",
            display_name="Mock",
            kind=ResearchProviderKind.SEARCH,
            status="ok",
            auth_state=ProviderAuthState.NOT_REQUIRED,
            configured=True,
        )
        citation = WebResearchCitation(
            title="Test",
            url="https://docs.python.org/3/",
            display_url="docs.python.org/3",
            domain="docs.python.org",
            provider_id="mock",
            trust_level=ResearchTrustLevel.SEARCH_INDEXED,
            trust_reason="Indexed",
        )
        mock_provider.search = AsyncMock(
            return_value=[
                WebResearchResult(
                    title="Python Docs",
                    url="https://docs.python.org/3/",
                    snippet="Official documentation",
                    provider_id="mock",
                    rank=1,
                    domain="docs.python.org",
                    trust_level=ResearchTrustLevel.SEARCH_INDEXED,
                    trust_reason="Indexed by mock",
                    citation=citation,
                    trust_label=TrustLabel.VERIFIED,
                    trust_label_reason="Authoritative source",
                ),
            ]
        )
        registry.register(mock_provider)
        registry.set_default("mock")

        tool = SearchTool(search_registry=registry)
        context = ToolContext()
        result = await tool.execute({"query": "python docs"}, context)
        assert result.success
        assert "Python Docs" in result.output
        assert "VERIFIED" in result.output
        assert "Provider: mock" in result.output

    async def test_search_all_providers_flag(self) -> None:
        from agent33.tools.builtin.search import SearchTool

        registry = SearchProviderRegistry()
        mock_provider = MagicMock()
        mock_provider.provider_id = "mock"
        mock_provider.diagnostics.return_value = ResearchProviderStatus(
            provider_id="mock",
            display_name="Mock",
            kind=ResearchProviderKind.SEARCH,
            status="ok",
            auth_state=ProviderAuthState.NOT_REQUIRED,
            configured=True,
        )
        mock_provider.search = AsyncMock(return_value=[])
        registry.register(mock_provider)

        tool = SearchTool(search_registry=registry)
        context = ToolContext()
        result = await tool.execute({"query": "test", "all_providers": True}, context)
        assert result.success
        assert "No results found" in result.output

    async def test_search_value_error_returns_fail(self) -> None:
        from agent33.tools.builtin.search import SearchTool

        registry = SearchProviderRegistry()
        mock_provider = MagicMock()
        mock_provider.provider_id = "mock"
        mock_provider.diagnostics.return_value = ResearchProviderStatus(
            provider_id="mock",
            display_name="Mock",
            kind=ResearchProviderKind.SEARCH,
            status="ok",
            auth_state=ProviderAuthState.NOT_REQUIRED,
            configured=True,
        )
        mock_provider.search = AsyncMock(side_effect=ValueError("Provider broken"))
        registry.register(mock_provider)
        registry.set_default("mock")

        tool = SearchTool(search_registry=registry)
        context = ToolContext()
        result = await tool.execute({"query": "test"}, context)
        assert not result.success
        assert "Provider broken" in result.error


# ---------------------------------------------------------------------------
# API route tests
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(autouse=True)
async def _install_search_registry() -> Any:
    """Install a mock-backed search registry on app.state for route tests."""
    registry = SearchProviderRegistry()

    mock_provider = MagicMock()
    mock_provider.provider_id = "duckduckgo"
    mock_provider.diagnostics.return_value = ResearchProviderStatus(
        provider_id="duckduckgo",
        display_name="DuckDuckGo",
        kind=ResearchProviderKind.SEARCH,
        status="ok",
        auth_state=ProviderAuthState.NOT_REQUIRED,
        configured=True,
        capabilities=["search", "snippets"],
        is_default=True,
        detail="Free search via DuckDuckGo HTML.",
    )
    citation = WebResearchCitation(
        title="Route Test Result",
        url="https://en.wikipedia.org/wiki/Test",
        display_url="en.wikipedia.org/wiki/Test",
        domain="en.wikipedia.org",
        provider_id="duckduckgo",
        trust_level=ResearchTrustLevel.SEARCH_INDEXED,
        trust_reason="Indexed by duckduckgo",
    )
    mock_provider.search = AsyncMock(
        return_value=[
            WebResearchResult(
                title="Route Test Result",
                url="https://en.wikipedia.org/wiki/Test",
                snippet="A test article from Wikipedia",
                provider_id="duckduckgo",
                rank=1,
                domain="en.wikipedia.org",
                display_url="en.wikipedia.org/wiki/Test",
                trust_level=ResearchTrustLevel.SEARCH_INDEXED,
                trust_reason="Indexed by duckduckgo",
                citation=citation,
                trust_label=TrustLabel.VERIFIED,
                trust_label_reason="Known authoritative source",
            ),
        ]
    )

    registry.register(mock_provider)
    registry.set_default("duckduckgo")

    # Also install mock web_research_service for legacy routes
    from agent33.api.routes.research import set_research_service
    from agent33.web_research.service import WebResearchService

    mock_legacy_search = MagicMock()
    mock_legacy_search.provider_id = "searxng"
    mock_legacy_search.diagnostics.return_value = ResearchProviderStatus(
        provider_id="searxng",
        display_name="SearXNG",
        kind=ResearchProviderKind.SEARCH,
        status="ok",
        auth_state=ProviderAuthState.NOT_REQUIRED,
        configured=True,
        capabilities=["search"],
        is_default=True,
    )
    mock_legacy_search.search = AsyncMock(return_value=[])

    mock_fetch = MagicMock()
    mock_fetch.provider_id = "web_fetch"
    mock_fetch.diagnostics.return_value = ResearchProviderStatus(
        provider_id="web_fetch",
        display_name="Governed HTTP Fetch",
        kind=ResearchProviderKind.FETCH,
        status="ok",
        auth_state=ProviderAuthState.NOT_REQUIRED,
        configured=True,
        capabilities=["fetch"],
    )
    mock_fetch.fetch = AsyncMock()

    legacy_service = WebResearchService(
        search_providers=[mock_legacy_search],
        fetch_providers=[mock_fetch],
        default_search_provider="searxng",
        default_fetch_provider="web_fetch",
        search_registry=registry,
    )

    original_registry = getattr(app.state, "search_provider_registry", None)
    original_service = getattr(app.state, "web_research_service", None)
    app.state.search_provider_registry = registry
    app.state.web_research_service = legacy_service

    from agent33.api.routes.web_research import set_search_provider_registry

    set_search_provider_registry(registry)
    set_research_service(legacy_service)

    yield registry

    set_search_provider_registry(None)
    set_research_service(None)
    if original_registry is not None:
        app.state.search_provider_registry = original_registry
    else:
        with contextlib.suppress(AttributeError):
            del app.state.search_provider_registry
    if original_service is not None:
        app.state.web_research_service = original_service
    else:
        with contextlib.suppress(AttributeError):
            del app.state.web_research_service


@pytest_asyncio.fixture()
async def async_client() -> Any:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


class TestWebResearchRoutes:
    """API route tests for /v1/web-research/*."""

    async def test_list_providers(self, async_client: httpx.AsyncClient) -> None:
        headers = _auth_headers(scopes=["tools:execute"])
        resp = await async_client.get("/v1/web-research/providers", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        # DuckDuckGo should be present
        ddg = next((p for p in data if p["provider_id"] == "duckduckgo"), None)
        assert ddg is not None
        assert ddg["display_name"] == "DuckDuckGo"
        assert ddg["configured"] is True
        assert ddg["is_default"] is True

    async def test_search_returns_results(self, async_client: httpx.AsyncClient) -> None:
        headers = _auth_headers(scopes=["tools:execute"])
        resp = await async_client.get(
            "/v1/web-research/search",
            params={"q": "test search", "limit": 5},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "test search"
        assert data["provider_id"] == "duckduckgo"
        assert len(data["results"]) == 1
        result = data["results"][0]
        assert result["title"] == "Route Test Result"
        assert result["trust_label"] == "verified"
        assert result["trust_label_reason"] == "Known authoritative source"

    async def test_search_with_provider_filter(self, async_client: httpx.AsyncClient) -> None:
        headers = _auth_headers(scopes=["tools:execute"])
        resp = await async_client.get(
            "/v1/web-research/search",
            params={"q": "test", "provider": "duckduckgo"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider_id"] == "duckduckgo"

    async def test_search_unknown_provider_returns_400(
        self, async_client: httpx.AsyncClient
    ) -> None:
        headers = _auth_headers(scopes=["tools:execute"])
        resp = await async_client.get(
            "/v1/web-research/search",
            params={"q": "test", "provider": "nonexistent"},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "Unknown" in resp.json()["detail"]

    async def test_search_all_providers(self, async_client: httpx.AsyncClient) -> None:
        headers = _auth_headers(scopes=["tools:execute"])
        resp = await async_client.get(
            "/v1/web-research/search",
            params={"q": "test", "all_providers": True},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["all_providers"] is True

    async def test_trust_domains_returns_entries(self, async_client: httpx.AsyncClient) -> None:
        headers = _auth_headers(scopes=["tools:execute"])
        resp = await async_client.get("/v1/web-research/trust-domains", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0
        labels = {entry["label"] for entry in data}
        assert "verified" in labels
        assert "community" in labels
        assert "suspicious" in labels
        # Each entry should have pattern and category
        for entry in data:
            assert "pattern" in entry
            assert "category" in entry
            assert "label" in entry

    async def test_trust_classify_verified_domain(self, async_client: httpx.AsyncClient) -> None:
        headers = _auth_headers(scopes=["tools:execute"])
        resp = await async_client.get(
            "/v1/web-research/trust-classify",
            params={"domain": "docs.python.org"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["domain"] == "docs.python.org"
        assert data["label"] == "verified"
        assert "authoritative" in data["reason"].lower()

    async def test_trust_classify_unknown_domain(self, async_client: httpx.AsyncClient) -> None:
        headers = _auth_headers(scopes=["tools:execute"])
        resp = await async_client.get(
            "/v1/web-research/trust-classify",
            params={"domain": "randomblog.com"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["label"] == "unknown"

    async def test_trust_classify_suspicious_domain(self, async_client: httpx.AsyncClient) -> None:
        headers = _auth_headers(scopes=["tools:execute"])
        resp = await async_client.get(
            "/v1/web-research/trust-classify",
            params={"domain": "spamsite.xyz"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["label"] == "suspicious"

    async def test_no_auth_returns_401(self, async_client: httpx.AsyncClient) -> None:
        resp = await async_client.get("/v1/web-research/providers")
        assert resp.status_code == 401

    async def test_wrong_scope_returns_403(self, async_client: httpx.AsyncClient) -> None:
        headers = _auth_headers(scopes=["agents:read"])
        resp = await async_client.get("/v1/web-research/providers", headers=headers)
        assert resp.status_code == 403

    async def test_search_empty_query_returns_422(self, async_client: httpx.AsyncClient) -> None:
        headers = _auth_headers(scopes=["tools:execute"])
        resp = await async_client.get(
            "/v1/web-research/search",
            params={"q": ""},
            headers=headers,
        )
        assert resp.status_code == 422
