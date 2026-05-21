"""Structured models for provider-aware web research."""

from __future__ import annotations

import re
from datetime import datetime  # noqa: TCH003 — Pydantic needs runtime access
from enum import StrEnum

from pydantic import BaseModel, Field


class ResearchTrustLevel(StrEnum):
    """Explicit trust semantics for research artifacts."""

    SEARCH_INDEXED = "search-indexed"
    FETCH_VERIFIED = "fetch-verified"
    BLOCKED = "blocked"


class TrustLabel(StrEnum):
    """Domain-reputation trust label for search results.

    These labels are heuristic, not a security guarantee. They provide a
    quick signal about the likely reliability of a source based on domain
    reputation patterns. Do NOT use these labels for security-critical
    access control decisions.
    """

    VERIFIED = "verified"
    COMMUNITY = "community"
    UNKNOWN = "unknown"
    SUSPICIOUS = "suspicious"


# ---------------------------------------------------------------------------
# Domain reputation heuristics
# ---------------------------------------------------------------------------

# Well-known authoritative domains: academic, government, major reference
# sites, and high-quality technical documentation.
_VERIFIED_DOMAIN_PATTERNS: list[re.Pattern[str]] = [
    # Government
    re.compile(r"\.gov$"),
    re.compile(r"\.gov\.[a-z]{2}$"),
    # Academic / education
    re.compile(r"\.edu$"),
    re.compile(r"\.ac\.[a-z]{2}$"),
    # Major reference / encyclopedias
    re.compile(r"(^|\.)wikipedia\.org$"),
    re.compile(r"(^|\.)wikimedia\.org$"),
    re.compile(r"(^|\.)britannica\.com$"),
    # Major tech documentation
    re.compile(r"(^|\.)docs\.python\.org$"),
    re.compile(r"(^|\.)docs\.microsoft\.com$"),
    re.compile(r"(^|\.)learn\.microsoft\.com$"),
    re.compile(r"(^|\.)developer\.mozilla\.org$"),
    re.compile(r"(^|\.)developer\.apple\.com$"),
    re.compile(r"(^|\.)developer\.android\.com$"),
    re.compile(r"(^|\.)cloud\.google\.com$"),
    re.compile(r"(^|\.)docs\.aws\.amazon\.com$"),
    re.compile(r"(^|\.)docs\.github\.com$"),
    # Major news / wire services
    re.compile(r"(^|\.)reuters\.com$"),
    re.compile(r"(^|\.)apnews\.com$"),
    re.compile(r"(^|\.)bbc\.co\.uk$"),
    re.compile(r"(^|\.)bbc\.com$"),
    re.compile(r"(^|\.)nytimes\.com$"),
    # Standards / RFCs
    re.compile(r"(^|\.)ietf\.org$"),
    re.compile(r"(^|\.)w3\.org$"),
    re.compile(r"(^|\.)rfc-editor\.org$"),
    # Scientific publishers
    re.compile(r"(^|\.)nature\.com$"),
    re.compile(r"(^|\.)science\.org$"),
    re.compile(r"(^|\.)arxiv\.org$"),
    re.compile(r"(^|\.)pubmed\.ncbi\.nlm\.nih\.gov$"),
]

# Community platforms: generally useful but user-generated content requires
# additional scrutiny.
_COMMUNITY_DOMAIN_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(^|\.)stackoverflow\.com$"),
    re.compile(r"(^|\.)stackexchange\.com$"),
    re.compile(r"(^|\.)github\.com$"),
    re.compile(r"(^|\.)gitlab\.com$"),
    re.compile(r"(^|\.)reddit\.com$"),
    re.compile(r"(^|\.)medium\.com$"),
    re.compile(r"(^|\.)dev\.to$"),
    re.compile(r"(^|\.)hackernews\.com$"),
    re.compile(r"(^|\.)news\.ycombinator\.com$"),
    re.compile(r"(^|\.)quora\.com$"),
    re.compile(r"(^|\.)discourse\.org$"),
]

# Known-suspicious patterns: domains associated with spam, content farms,
# or deceptive practices. This is illustrative, not exhaustive.
_SUSPICIOUS_DOMAIN_PATTERNS: list[re.Pattern[str]] = [
    # Common content farm / SEO spam TLDs and patterns
    re.compile(r"\.(xyz|top|click|loan|work|gq|cf|tk|ml|ga)$"),
    # Extremely long subdomains (common in phishing)
    re.compile(r"^[^.]{50,}\."),
    # IP addresses as domains
    re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"),
]


def classify_domain_trust(domain: str) -> tuple[TrustLabel, str]:
    """Classify a domain into a trust label with a human-readable reason.

    Returns a (label, reason) tuple. The classification is purely heuristic
    and should not be used as a security boundary.
    """
    if not domain:
        return TrustLabel.UNKNOWN, "No domain information available."

    domain_lower = domain.lower().strip()

    for pattern in _VERIFIED_DOMAIN_PATTERNS:
        if pattern.search(domain_lower):
            return (
                TrustLabel.VERIFIED,
                f"Domain '{domain_lower}' matches a known authoritative source pattern.",
            )

    for pattern in _COMMUNITY_DOMAIN_PATTERNS:
        if pattern.search(domain_lower):
            return (
                TrustLabel.COMMUNITY,
                f"Domain '{domain_lower}' is a known community platform; "
                f"content is user-generated and may vary in quality.",
            )

    for pattern in _SUSPICIOUS_DOMAIN_PATTERNS:
        if pattern.search(domain_lower):
            return (
                TrustLabel.SUSPICIOUS,
                f"Domain '{domain_lower}' matches a suspicious pattern; "
                f"exercise extra caution with this source.",
            )

    return (
        TrustLabel.UNKNOWN,
        f"Domain '{domain_lower}' has no established reputation in our heuristics.",
    )


class TrustedDomainEntry(BaseModel):
    """A trusted domain pattern for the trust-domains API."""

    pattern: str
    label: TrustLabel
    category: str


class ResearchProviderKind(StrEnum):
    """Kinds of web research providers."""

    SEARCH = "search"
    FETCH = "fetch"


class ProviderAuthState(StrEnum):
    """Configuration/auth state for a research provider."""

    NOT_REQUIRED = "not_required"
    CONFIGURED = "configured"
    MISSING = "missing"


class WebResearchCitation(BaseModel):
    """Citation metadata suitable for direct frontend rendering."""

    title: str
    url: str
    display_url: str
    domain: str
    provider_id: str
    trust_level: ResearchTrustLevel
    trust_reason: str


class WebResearchResult(BaseModel):
    """A structured web search result."""

    title: str
    url: str
    snippet: str = ""
    provider_id: str
    rank: int = 1
    domain: str = ""
    display_url: str = ""
    trust_level: ResearchTrustLevel
    trust_reason: str
    citation: WebResearchCitation
    trust_label: TrustLabel = TrustLabel.UNKNOWN
    trust_label_reason: str = ""
    published_date: str | None = None
    relevance_score: float = 0.0


class ResearchProviderStatus(BaseModel):
    """Operator-visible diagnostics for a research provider."""

    provider_id: str
    display_name: str
    kind: ResearchProviderKind
    status: str
    auth_state: ProviderAuthState
    configured: bool
    capabilities: list[str] = Field(default_factory=list)
    is_default: bool = False
    detail: str = ""


class ProviderStatusInfo(BaseModel):
    """Dashboard-facing provider health summary with call metrics."""

    name: str
    enabled: bool
    status: str
    last_check: datetime | None = None
    total_calls: int = 0
    success_rate: float = 1.0


class ResearchSearchRequest(BaseModel):
    """Search request body for grounded web research."""

    query: str = Field(min_length=1)
    provider: str | None = None
    limit: int = Field(default=10, ge=1, le=25)
    categories: str = "general"


class ResearchSearchResponse(BaseModel):
    """Structured search response for the web research API."""

    query: str
    provider_id: str
    results: list[WebResearchResult] = Field(default_factory=list)


class ResearchFetchRequest(BaseModel):
    """Fetch request body for governed web retrieval."""

    url: str = Field(min_length=1)
    method: str = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    body: str | None = None
    timeout: int = Field(default=30, ge=1, le=300)
    allowed_domains: list[str] = Field(default_factory=list)


class WebFetchArtifact(BaseModel):
    """Structured representation of a fetched page."""

    url: str
    provider_id: str
    status_code: int
    content: str
    content_preview: str
    trust_level: ResearchTrustLevel
    trust_reason: str
    citation: WebResearchCitation
