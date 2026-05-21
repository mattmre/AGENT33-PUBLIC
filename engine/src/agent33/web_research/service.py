"""Provider-aware web research service layer.

Supports multiple search providers (SearXNG, Tavily, Brave, DuckDuckGo) with
automatic discovery based on configured API keys. DuckDuckGo works without any
API key as a zero-config fallback.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol
from urllib.parse import quote_plus, urlparse

if TYPE_CHECKING:
    from collections.abc import Sequence

import httpx

from agent33.config import settings
from agent33.connectors.boundary import (
    build_connector_boundary_executor,
    map_connector_exception,
)
from agent33.connectors.models import ConnectorRequest
from agent33.web_research.models import (
    ProviderAuthState,
    ProviderStatusInfo,
    ResearchProviderKind,
    ResearchProviderStatus,
    ResearchSearchResponse,
    ResearchTrustLevel,
    TrustedDomainEntry,
    TrustLabel,
    WebFetchArtifact,
    WebResearchCitation,
    WebResearchResult,
    classify_domain_trust,
)

logger = logging.getLogger(__name__)

_SEARCH_TIMEOUT_SECONDS = 15.0
_FETCH_TIMEOUT_SECONDS = 30.0
_MAX_FETCH_BYTES = 5 * 1024 * 1024


class SearchProvider(Protocol):
    """Protocol for search-capable research providers."""

    provider_id: str

    def diagnostics(self) -> ResearchProviderStatus:
        """Return operator-visible provider diagnostics."""

    async def search(
        self,
        query: str,
        *,
        limit: int,
        categories: str,
    ) -> list[WebResearchResult]:
        """Execute a search query and return structured results."""


class FetchProvider(Protocol):
    """Protocol for fetch-capable research providers."""

    provider_id: str

    def diagnostics(self) -> ResearchProviderStatus:
        """Return operator-visible provider diagnostics."""

    async def fetch(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: str | None,
        method: str,
        timeout: int,
        allowed_domains: Sequence[str],
    ) -> WebFetchArtifact:
        """Fetch a URL and return a structured artifact."""


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _display_url(url: str) -> str:
    parsed = urlparse(url)
    domain = parsed.netloc or parsed.path
    path = parsed.path.rstrip("/")
    if path:
        return f"{domain}{path}"
    return domain or url


def _domain(url: str) -> str:
    return urlparse(url).hostname or ""


def _search_citation(title: str, url: str, provider_id: str) -> WebResearchCitation:
    return WebResearchCitation(
        title=title,
        url=url,
        display_url=_display_url(url),
        domain=_domain(url),
        provider_id=provider_id,
        trust_level=ResearchTrustLevel.SEARCH_INDEXED,
        trust_reason=(
            f"Indexed by {provider_id}; AGENT-33 has not fetched this source directly yet."
        ),
    )


def _build_result(
    *,
    title: str,
    url: str,
    snippet: str,
    provider_id: str,
    rank: int,
    published_date: str | None = None,
    relevance_score: float = 0.0,
) -> WebResearchResult:
    """Build a WebResearchResult with trust labels applied."""
    citation = _search_citation(title, url, provider_id)
    domain = citation.domain
    trust_label, trust_label_reason = classify_domain_trust(domain)
    return WebResearchResult(
        title=title,
        url=url,
        snippet=snippet,
        provider_id=provider_id,
        rank=rank,
        domain=domain,
        display_url=citation.display_url,
        trust_level=citation.trust_level,
        trust_reason=citation.trust_reason,
        citation=citation,
        trust_label=trust_label,
        trust_label_reason=trust_label_reason,
        published_date=published_date,
        relevance_score=relevance_score,
    )


# ---------------------------------------------------------------------------
# SearXNG provider (existing, upgraded with trust labels)
# ---------------------------------------------------------------------------


class SearXNGSearchProvider:
    """Search provider backed by a self-hosted SearXNG instance."""

    provider_id = "searxng"

    def diagnostics(self) -> ResearchProviderStatus:
        configured = bool(settings.searxng_url and settings.searxng_url.strip())
        return ResearchProviderStatus(
            provider_id=self.provider_id,
            display_name="SearXNG",
            kind=ResearchProviderKind.SEARCH,
            status="ok" if configured else "unconfigured",
            auth_state=ProviderAuthState.NOT_REQUIRED,
            configured=configured,
            capabilities=["search", "snippets", "categories"],
            is_default=False,
            detail=(
                f"Base URL: {settings.searxng_url}"
                if configured
                else "Set `SEARXNG_URL` to enable SearXNG search."
            ),
        )

    async def search(
        self,
        query: str,
        *,
        limit: int,
        categories: str,
    ) -> list[WebResearchResult]:
        if not settings.searxng_url or not settings.searxng_url.strip():
            raise ValueError("SearXNG provider is not configured")

        url = f"{settings.searxng_url}/search"
        request_params: dict[str, str | int] = {
            "q": query,
            "format": "json",
            "pageno": 1,
            "categories": categories,
        }

        async def _perform_search(_request: ConnectorRequest) -> httpx.Response:
            async with httpx.AsyncClient(timeout=_SEARCH_TIMEOUT_SECONDS) as client:
                return await client.get(url, params=request_params)

        boundary_executor = build_connector_boundary_executor(
            default_timeout_seconds=_SEARCH_TIMEOUT_SECONDS,
            retry_attempts=1,
        )
        try:
            if boundary_executor is None:
                response = await _perform_search(
                    ConnectorRequest(connector="search:searxng", operation="GET")
                )
            else:
                req = ConnectorRequest(
                    connector="search:searxng",
                    operation="GET",
                    payload={"url": url, "params": request_params},
                    metadata={"timeout_seconds": _SEARCH_TIMEOUT_SECONDS},
                )
                response = await boundary_executor.execute(req, _perform_search)
            response.raise_for_status()
        except Exception as exc:
            if boundary_executor is not None:
                mapped = map_connector_exception(exc, "search:searxng", "GET")
                raise ValueError(str(mapped)) from exc
            if isinstance(exc, httpx.ConnectError):
                raise ValueError(
                    f"Could not connect to SearXNG at {settings.searxng_url}."
                ) from exc
            if isinstance(exc, httpx.TimeoutException):
                raise ValueError("SearXNG request timed out.") from exc
            if isinstance(exc, httpx.HTTPStatusError):
                raise ValueError(
                    f"SearXNG returned HTTP {exc.response.status_code}: {exc.response.text[:500]}"
                ) from exc
            if isinstance(exc, httpx.RequestError):
                raise ValueError(f"SearXNG request error: {exc}") from exc
            raise ValueError(f"SearXNG request error: {exc}") from exc

        payload = response.json()
        raw_results = payload.get("results", [])[:limit]
        results: list[WebResearchResult] = []
        for index, item in enumerate(raw_results, start=1):
            results.append(
                _build_result(
                    title=str(item.get("title") or "Untitled"),
                    url=str(item.get("url") or ""),
                    snippet=str(item.get("content") or "").strip(),
                    provider_id=self.provider_id,
                    rank=index,
                    published_date=str(item.get("publishedDate") or "") or None,
                )
            )
        return results


# ---------------------------------------------------------------------------
# DuckDuckGo provider (free, no API key required)
# ---------------------------------------------------------------------------


class DuckDuckGoSearchProvider:
    """Free search provider using DuckDuckGo's HTML search.

    This provider uses DuckDuckGo's HTML-based search (``html.duckduckgo.com``)
    which requires no API key and no third-party library. It serves as the
    zero-config fallback when no other search provider API keys are configured.

    The HTML response is parsed to extract result links, titles, and snippets.
    """

    provider_id = "duckduckgo"

    def diagnostics(self) -> ResearchProviderStatus:
        return ResearchProviderStatus(
            provider_id=self.provider_id,
            display_name="DuckDuckGo",
            kind=ResearchProviderKind.SEARCH,
            status="ok",
            auth_state=ProviderAuthState.NOT_REQUIRED,
            configured=True,
            capabilities=["search", "snippets"],
            is_default=True,
            detail="Free search via DuckDuckGo HTML. No API key required.",
        )

    async def search(
        self,
        query: str,
        *,
        limit: int,
        categories: str,
    ) -> list[WebResearchResult]:
        """Search DuckDuckGo via its HTML endpoint and parse results."""
        encoded_query = quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded_query}"

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }

        try:
            async with httpx.AsyncClient(
                timeout=_SEARCH_TIMEOUT_SECONDS,
                follow_redirects=True,
            ) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
        except httpx.ConnectError as exc:
            raise ValueError("Could not connect to DuckDuckGo.") from exc
        except httpx.TimeoutException as exc:
            raise ValueError("DuckDuckGo request timed out.") from exc
        except httpx.HTTPStatusError as exc:
            raise ValueError(f"DuckDuckGo returned HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise ValueError(f"DuckDuckGo request error: {exc}") from exc

        return self._parse_html_results(response.text, limit)

    def _parse_html_results(self, html: str, limit: int) -> list[WebResearchResult]:
        """Parse DuckDuckGo HTML response to extract search results.

        The HTML search page uses ``<a class="result__a">`` for result links
        and ``<a class="result__snippet">`` for snippets.
        """
        import re

        results: list[WebResearchResult] = []

        # DuckDuckGo HTML results are in divs with class "result"
        # Each result has a link (class="result__a") and snippet (class="result__snippet")
        link_pattern = re.compile(
            r'<a\s+[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
            re.DOTALL,
        )
        snippet_pattern = re.compile(
            r'<a\s+[^>]*class="result__snippet"[^>]*>(.*?)</a>',
            re.DOTALL,
        )

        links = link_pattern.findall(html)
        snippets = snippet_pattern.findall(html)

        for index, (href, raw_title) in enumerate(links[:limit], start=1):
            # Clean HTML tags from title and snippet
            title = re.sub(r"<[^>]+>", "", raw_title).strip()
            snippet = ""
            if index - 1 < len(snippets):
                snippet = re.sub(r"<[^>]+>", "", snippets[index - 1]).strip()

            # DuckDuckGo redirects through uddg parameter
            actual_url = href
            uddg_match = re.search(r"uddg=([^&]+)", href)
            if uddg_match:
                from urllib.parse import unquote

                actual_url = unquote(uddg_match.group(1))

            if not title or not actual_url or actual_url.startswith("javascript:"):
                continue

            results.append(
                _build_result(
                    title=title,
                    url=actual_url,
                    snippet=snippet,
                    provider_id=self.provider_id,
                    rank=index,
                )
            )

        return results


# ---------------------------------------------------------------------------
# Tavily provider (requires TAVILY_API_KEY)
# ---------------------------------------------------------------------------


class TavilySearchProvider:
    """Search provider backed by the Tavily Search API.

    Requires ``TAVILY_API_KEY`` environment variable. Tavily provides
    AI-optimized search results with relevance scores and optional
    answer generation.
    """

    provider_id = "tavily"

    def _api_key(self) -> str:
        return settings.tavily_api_key.get_secret_value() if settings.tavily_api_key else ""

    def diagnostics(self) -> ResearchProviderStatus:
        has_key = bool(self._api_key())
        return ResearchProviderStatus(
            provider_id=self.provider_id,
            display_name="Tavily",
            kind=ResearchProviderKind.SEARCH,
            status="ok" if has_key else "unconfigured",
            auth_state=ProviderAuthState.CONFIGURED if has_key else ProviderAuthState.MISSING,
            configured=has_key,
            capabilities=["search", "snippets", "relevance_scores", "ai_optimized"],
            detail=(
                "Tavily Search API configured."
                if has_key
                else "Set `TAVILY_API_KEY` to enable Tavily search."
            ),
        )

    async def search(
        self,
        query: str,
        *,
        limit: int,
        categories: str,
    ) -> list[WebResearchResult]:
        api_key = self._api_key()
        if not api_key:
            raise ValueError("Tavily provider is not configured (missing TAVILY_API_KEY)")

        url = "https://api.tavily.com/search"
        payload = {
            "api_key": api_key,
            "query": query,
            "max_results": limit,
            "include_answer": False,
            "search_depth": "basic",
        }

        try:
            async with httpx.AsyncClient(timeout=_SEARCH_TIMEOUT_SECONDS) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
        except httpx.ConnectError as exc:
            raise ValueError("Could not connect to Tavily API.") from exc
        except httpx.TimeoutException as exc:
            raise ValueError("Tavily request timed out.") from exc
        except httpx.HTTPStatusError as exc:
            raise ValueError(
                f"Tavily returned HTTP {exc.response.status_code}: {exc.response.text[:500]}"
            ) from exc
        except httpx.RequestError as exc:
            raise ValueError(f"Tavily request error: {exc}") from exc

        data = response.json()
        raw_results = data.get("results", [])[:limit]
        results: list[WebResearchResult] = []
        for index, item in enumerate(raw_results, start=1):
            results.append(
                _build_result(
                    title=str(item.get("title") or "Untitled"),
                    url=str(item.get("url") or ""),
                    snippet=str(item.get("content") or "").strip(),
                    provider_id=self.provider_id,
                    rank=index,
                    published_date=str(item.get("published_date") or "") or None,
                    relevance_score=float(item.get("score", 0.0)),
                )
            )
        return results


# ---------------------------------------------------------------------------
# Brave Search provider (requires BRAVE_API_KEY)
# ---------------------------------------------------------------------------


class BraveSearchProvider:
    """Search provider backed by the Brave Search API.

    Requires ``BRAVE_API_KEY`` environment variable. Uses the Brave Web
    Search API (``api.search.brave.com/res/v1/web/search``).
    """

    provider_id = "brave"

    def _api_key(self) -> str:
        return settings.brave_api_key.get_secret_value() if settings.brave_api_key else ""

    def diagnostics(self) -> ResearchProviderStatus:
        has_key = bool(self._api_key())
        return ResearchProviderStatus(
            provider_id=self.provider_id,
            display_name="Brave Search",
            kind=ResearchProviderKind.SEARCH,
            status="ok" if has_key else "unconfigured",
            auth_state=ProviderAuthState.CONFIGURED if has_key else ProviderAuthState.MISSING,
            configured=has_key,
            capabilities=["search", "snippets"],
            detail=(
                "Brave Search API configured."
                if has_key
                else "Set `BRAVE_API_KEY` to enable Brave Search."
            ),
        )

    async def search(
        self,
        query: str,
        *,
        limit: int,
        categories: str,
    ) -> list[WebResearchResult]:
        api_key = self._api_key()
        if not api_key:
            raise ValueError("Brave provider is not configured (missing BRAVE_API_KEY)")

        url = "https://api.search.brave.com/res/v1/web/search"
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": api_key,
        }
        params = {
            "q": query,
            "count": str(min(limit, 20)),
        }

        try:
            async with httpx.AsyncClient(timeout=_SEARCH_TIMEOUT_SECONDS) as client:
                response = await client.get(url, headers=headers, params=params)
                response.raise_for_status()
        except httpx.ConnectError as exc:
            raise ValueError("Could not connect to Brave Search API.") from exc
        except httpx.TimeoutException as exc:
            raise ValueError("Brave Search request timed out.") from exc
        except httpx.HTTPStatusError as exc:
            raise ValueError(
                f"Brave Search returned HTTP {exc.response.status_code}: {exc.response.text[:500]}"
            ) from exc
        except httpx.RequestError as exc:
            raise ValueError(f"Brave Search request error: {exc}") from exc

        data = response.json()
        web_results = data.get("web", {}).get("results", [])[:limit]
        results: list[WebResearchResult] = []
        for index, item in enumerate(web_results, start=1):
            results.append(
                _build_result(
                    title=str(item.get("title") or "Untitled"),
                    url=str(item.get("url") or ""),
                    snippet=str(item.get("description") or "").strip(),
                    provider_id=self.provider_id,
                    rank=index,
                    published_date=str(item.get("page_age") or "") or None,
                )
            )
        return results


# ---------------------------------------------------------------------------
# Governed fetch provider (unchanged)
# ---------------------------------------------------------------------------


class GovernedFetchProvider:
    """Fetch provider that wraps governed HTTP retrieval."""

    provider_id = "web_fetch"

    def diagnostics(self) -> ResearchProviderStatus:
        return ResearchProviderStatus(
            provider_id=self.provider_id,
            display_name="Governed HTTP Fetch",
            kind=ResearchProviderKind.FETCH,
            status="ok",
            auth_state=ProviderAuthState.NOT_REQUIRED,
            configured=True,
            capabilities=["fetch", "allowlist-enforced"],
            detail="Uses connector-boundary execution with explicit domain allowlists.",
        )

    async def fetch(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: str | None,
        method: str,
        timeout: int,
        allowed_domains: Sequence[str],
    ) -> WebFetchArtifact:
        domain = _domain(url)
        if not allowed_domains:
            raise ValueError("Domain allowlist not configured — all requests denied by default")
        if not any(
            domain == allowed or domain.endswith(f".{allowed}") for allowed in allowed_domains
        ):
            raise ValueError(f"Domain '{domain}' is not in the allowlist: {list(allowed_domains)}")

        async def _perform_fetch(_request: ConnectorRequest) -> httpx.Response:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                if method == "GET":
                    return await client.get(url, headers=headers)
                return await client.post(url, headers=headers, content=body)

        boundary_executor = build_connector_boundary_executor(
            default_timeout_seconds=float(timeout),
            retry_attempts=1,
        )
        try:
            if boundary_executor is None:
                response = await _perform_fetch(
                    ConnectorRequest(connector="tool:web_fetch", operation=method)
                )
            else:
                req = ConnectorRequest(
                    connector="tool:web_fetch",
                    operation=method,
                    payload={"url": url, "headers": headers, "body": body},
                    metadata={"timeout_seconds": float(timeout)},
                )
                response = await boundary_executor.execute(req, _perform_fetch)
            response.raise_for_status()
            if 300 <= response.status_code < 400:
                raise ValueError("Redirect responses are blocked by policy")
            if len(response.content) > _MAX_FETCH_BYTES:
                raise ValueError(
                    f"Response too large ({len(response.content)} bytes, limit {_MAX_FETCH_BYTES})"
                )
        except Exception as exc:
            if boundary_executor is not None and not isinstance(exc, ValueError):
                mapped = map_connector_exception(exc, "tool:web_fetch", method)
                raise ValueError(str(mapped)) from exc
            if isinstance(exc, ValueError):
                raise
            if isinstance(exc, httpx.TimeoutException):
                raise ValueError(f"Request timed out after {timeout}s") from exc
            if isinstance(exc, httpx.HTTPStatusError):
                raise ValueError(
                    f"HTTP {exc.response.status_code}: {exc.response.text[:500]}"
                ) from exc
            if isinstance(exc, httpx.RequestError):
                raise ValueError(f"Request error: {exc}") from exc
            raise ValueError(f"Request error: {exc}") from exc

        citation = WebResearchCitation(
            title=_display_url(url),
            url=url,
            display_url=_display_url(url),
            domain=domain,
            provider_id=self.provider_id,
            trust_level=ResearchTrustLevel.FETCH_VERIFIED,
            trust_reason="Fetched directly by AGENT-33 through the governed web_fetch provider.",
        )
        content = response.text
        return WebFetchArtifact(
            url=url,
            provider_id=self.provider_id,
            status_code=response.status_code,
            content=content,
            content_preview=content[:2000],
            trust_level=ResearchTrustLevel.FETCH_VERIFIED,
            trust_reason=citation.trust_reason,
            citation=citation,
        )


# ---------------------------------------------------------------------------
# Search provider registry
# ---------------------------------------------------------------------------


class SearchProviderRegistry:
    """Registry that auto-discovers available search providers based on config.

    Providers are registered based on which API keys / config values are set.
    DuckDuckGo is always available as a zero-config fallback.
    """

    def __init__(self) -> None:
        self._providers: dict[str, SearchProvider] = {}
        self._default_provider_id: str = "duckduckgo"

    def register(self, provider: SearchProvider) -> None:
        """Register a search provider."""
        self._providers[provider.provider_id] = provider
        logger.info("Registered search provider: %s", provider.provider_id)

    def set_default(self, provider_id: str) -> None:
        """Set the default provider ID."""
        if provider_id not in self._providers:
            logger.warning("Cannot set default to '%s': provider not registered", provider_id)
            return
        self._default_provider_id = provider_id
        logger.info("Default search provider set to: %s", provider_id)

    @property
    def default_provider_id(self) -> str:
        return self._default_provider_id

    def get(self, provider_id: str) -> SearchProvider | None:
        """Get a provider by ID."""
        return self._providers.get(provider_id)

    def list_providers(self) -> list[SearchProvider]:
        """Return all registered providers."""
        return list(self._providers.values())

    def list_provider_ids(self) -> list[str]:
        """Return IDs of all registered providers."""
        return list(self._providers.keys())

    def list_diagnostics(self) -> list[ResearchProviderStatus]:
        """Return diagnostics for all registered providers."""
        result = []
        for provider in self._providers.values():
            diag = provider.diagnostics()
            # Mark the default
            if provider.provider_id == self._default_provider_id:
                diag = diag.model_copy(update={"is_default": True})
            result.append(diag)
        return result

    async def search(
        self,
        query: str,
        *,
        provider_id: str | None = None,
        limit: int = 10,
        categories: str = "general",
    ) -> list[WebResearchResult]:
        """Execute a search with the specified or default provider."""
        resolved_id = provider_id or self._default_provider_id
        provider = self._providers.get(resolved_id)
        if provider is None:
            raise ValueError(f"Unknown search provider '{resolved_id}'")
        return await provider.search(query, limit=limit, categories=categories)

    async def search_all(
        self,
        query: str,
        *,
        limit: int = 10,
        categories: str = "general",
    ) -> list[WebResearchResult]:
        """Query all configured providers and aggregate + deduplicate results.

        Results are deduplicated by URL, keeping the first occurrence (from
        the provider encountered first). Trust labels are applied during
        result construction.
        """
        all_results: list[WebResearchResult] = []
        seen_urls: set[str] = set()

        for provider in self._providers.values():
            diag = provider.diagnostics()
            if not diag.configured:
                continue
            try:
                results = await provider.search(query, limit=limit, categories=categories)
                for r in results:
                    normalized_url = r.url.rstrip("/").lower()
                    if normalized_url not in seen_urls:
                        seen_urls.add(normalized_url)
                        all_results.append(r)
            except Exception:
                logger.warning(
                    "Provider '%s' failed during search_all",
                    provider.provider_id,
                    exc_info=True,
                )
                continue

        return all_results

    def get_trust_domain_entries(self) -> list[TrustedDomainEntry]:
        """Return the domain trust heuristic patterns for API exposure."""
        from agent33.web_research.models import (
            _COMMUNITY_DOMAIN_PATTERNS,
            _SUSPICIOUS_DOMAIN_PATTERNS,
            _VERIFIED_DOMAIN_PATTERNS,
        )

        entries: list[TrustedDomainEntry] = []
        for p in _VERIFIED_DOMAIN_PATTERNS:
            entries.append(
                TrustedDomainEntry(
                    pattern=p.pattern, label=TrustLabel.VERIFIED, category="verified"
                )
            )
        for p in _COMMUNITY_DOMAIN_PATTERNS:
            entries.append(
                TrustedDomainEntry(
                    pattern=p.pattern, label=TrustLabel.COMMUNITY, category="community"
                )
            )
        for p in _SUSPICIOUS_DOMAIN_PATTERNS:
            entries.append(
                TrustedDomainEntry(
                    pattern=p.pattern, label=TrustLabel.SUSPICIOUS, category="suspicious"
                )
            )
        return entries


def create_search_provider_registry() -> SearchProviderRegistry:
    """Build and populate a SearchProviderRegistry from current settings.

    Providers are registered based on configuration:
    - DuckDuckGo: always registered (no API key needed)
    - SearXNG: registered if ``SEARXNG_URL`` is set
    - Tavily: registered if ``TAVILY_API_KEY`` is set
    - Brave: registered if ``BRAVE_API_KEY`` is set

    The default provider is chosen as:
    1. ``web_search_default_provider`` from settings, if set and available
    2. Tavily, if configured (highest-quality API results)
    3. Brave, if configured
    4. SearXNG, if configured
    5. DuckDuckGo (always available)
    """
    registry = SearchProviderRegistry()

    # Always register DuckDuckGo as the free fallback
    registry.register(DuckDuckGoSearchProvider())

    # SearXNG (self-hosted, no API key required but needs URL)
    if settings.searxng_url and settings.searxng_url.strip():
        registry.register(SearXNGSearchProvider())

    # Tavily (API key required)
    tavily_key = settings.tavily_api_key.get_secret_value() if settings.tavily_api_key else ""
    if tavily_key:
        registry.register(TavilySearchProvider())

    # Brave (API key required)
    brave_key = settings.brave_api_key.get_secret_value() if settings.brave_api_key else ""
    if brave_key:
        registry.register(BraveSearchProvider())

    # Choose default provider
    default_pref = getattr(settings, "web_search_default_provider", None)
    if default_pref and registry.get(default_pref):
        registry.set_default(default_pref)
    elif tavily_key:
        registry.set_default("tavily")
    elif brave_key:
        registry.set_default("brave")
    elif settings.searxng_url and settings.searxng_url.strip():
        registry.set_default("searxng")
    # else: default stays "duckduckgo"

    return registry


# ---------------------------------------------------------------------------
# WebResearchService (upgraded to use SearchProviderRegistry)
# ---------------------------------------------------------------------------


class WebResearchService:
    """Unified service for grounded search/fetch providers."""

    def __init__(
        self,
        *,
        search_providers: Sequence[SearchProvider],
        fetch_providers: Sequence[FetchProvider],
        default_search_provider: str,
        default_fetch_provider: str,
        search_registry: SearchProviderRegistry | None = None,
    ) -> None:
        self._search_providers = {provider.provider_id: provider for provider in search_providers}
        self._fetch_providers = {provider.provider_id: provider for provider in fetch_providers}
        self._default_search_provider = default_search_provider
        self._default_fetch_provider = default_fetch_provider
        self._search_registry = search_registry

    @property
    def search_registry(self) -> SearchProviderRegistry | None:
        return self._search_registry

    def list_providers(self) -> list[ResearchProviderStatus]:
        providers = [provider.diagnostics() for provider in self._search_providers.values()]
        providers.extend(provider.diagnostics() for provider in self._fetch_providers.values())
        return providers

    def provider_status_summary(self) -> list[ProviderStatusInfo]:
        """Build a dashboard-friendly health summary for each provider."""
        summaries: list[ProviderStatusInfo] = []
        for diag in self.list_providers():
            summaries.append(
                ProviderStatusInfo(
                    name=diag.display_name,
                    enabled=diag.configured,
                    status=diag.status,
                    last_check=None,
                    total_calls=0,
                    success_rate=1.0,
                )
            )
        return summaries

    async def search(
        self,
        query: str,
        *,
        provider_id: str | None = None,
        limit: int = 10,
        categories: str = "general",
    ) -> ResearchSearchResponse:
        resolved_provider_id = provider_id or self._default_search_provider
        provider = self._search_providers.get(resolved_provider_id)
        if provider is None:
            raise ValueError(f"Unknown research search provider '{resolved_provider_id}'")
        results = await provider.search(query, limit=limit, categories=categories)
        return ResearchSearchResponse(
            query=query,
            provider_id=resolved_provider_id,
            results=results,
        )

    async def fetch(
        self,
        url: str,
        *,
        allowed_domains: Sequence[str],
        provider_id: str | None = None,
        headers: dict[str, str] | None = None,
        body: str | None = None,
        method: str = "GET",
        timeout: int = int(_FETCH_TIMEOUT_SECONDS),
    ) -> WebFetchArtifact:
        resolved_provider_id = provider_id or self._default_fetch_provider
        provider = self._fetch_providers.get(resolved_provider_id)
        if provider is None:
            raise ValueError(f"Unknown research fetch provider '{resolved_provider_id}'")
        return await provider.fetch(
            url,
            headers=headers or {},
            body=body,
            method=method,
            timeout=timeout,
            allowed_domains=allowed_domains,
        )


def create_default_web_research_service(
    *,
    search_registry: SearchProviderRegistry | None = None,
) -> WebResearchService:
    """Create the default Track 7 research service graph.

    If a SearchProviderRegistry is provided, its providers are included in the
    service. Otherwise only the legacy SearXNG + GovernedFetch providers are used.
    """
    search_providers: list[SearchProvider] = [SearXNGSearchProvider()]
    default_search = "searxng"

    # Merge registry providers into the service if available
    if search_registry is not None:
        for provider in search_registry.list_providers():
            if provider.provider_id not in {p.provider_id for p in search_providers}:
                search_providers.append(provider)
        default_search = search_registry.default_provider_id

    return WebResearchService(
        search_providers=search_providers,
        fetch_providers=[GovernedFetchProvider()],
        default_search_provider=default_search,
        default_fetch_provider="web_fetch",
        search_registry=search_registry,
    )
