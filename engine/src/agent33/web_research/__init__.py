"""Provider-aware web research services."""

from agent33.web_research.models import (
    ProviderStatusInfo,
    ResearchFetchRequest,
    ResearchProviderStatus,
    ResearchSearchRequest,
    ResearchSearchResponse,
    ResearchTrustLevel,
    TrustedDomainEntry,
    TrustLabel,
    WebFetchArtifact,
    WebResearchCitation,
    WebResearchResult,
    classify_domain_trust,
)
from agent33.web_research.service import (
    BraveSearchProvider,
    DuckDuckGoSearchProvider,
    SearchProviderRegistry,
    SearXNGSearchProvider,
    TavilySearchProvider,
    WebResearchService,
    create_default_web_research_service,
    create_search_provider_registry,
)

__all__ = [
    "BraveSearchProvider",
    "DuckDuckGoSearchProvider",
    "ProviderStatusInfo",
    "ResearchFetchRequest",
    "ResearchProviderStatus",
    "ResearchSearchRequest",
    "ResearchSearchResponse",
    "ResearchTrustLevel",
    "SearchProviderRegistry",
    "SearXNGSearchProvider",
    "TavilySearchProvider",
    "TrustLabel",
    "TrustedDomainEntry",
    "WebFetchArtifact",
    "WebResearchCitation",
    "WebResearchResult",
    "WebResearchService",
    "classify_domain_trust",
    "create_default_web_research_service",
    "create_search_provider_registry",
]
