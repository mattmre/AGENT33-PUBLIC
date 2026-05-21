"""Provider diagnostics and web search routes for Track 7.

Exposes the ``SearchProviderRegistry`` through REST endpoints for provider
enumeration, trust domain inspection, and direct search execution.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from agent33.security.permissions import require_scope
from agent33.web_research.models import (
    ResearchProviderStatus,
    TrustedDomainEntry,
    TrustLabel,
    WebResearchResult,
    classify_domain_trust,
)

if TYPE_CHECKING:
    from agent33.web_research.service import SearchProviderRegistry

router = APIRouter(prefix="/v1/web-research", tags=["web-research"])

_search_registry: SearchProviderRegistry | None = None


def set_search_provider_registry(registry: SearchProviderRegistry | None) -> None:
    """Set the module-level registry reference (called from lifespan)."""
    global _search_registry  # noqa: PLW0603
    _search_registry = registry


def _get_registry(request: Request) -> SearchProviderRegistry:
    if _search_registry is not None:
        return _search_registry
    reg: Any = getattr(request.app.state, "search_provider_registry", None)
    if reg is not None:
        return reg  # type: ignore[no-any-return]
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Search provider registry not initialized",
    )


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class WebSearchResponse(BaseModel):
    """Structured response for the web research search endpoint."""

    query: str
    provider_id: str | None = None
    all_providers: bool = False
    results: list[WebResearchResult] = Field(default_factory=list)


class TrustClassificationResponse(BaseModel):
    """Response from domain trust classification."""

    domain: str
    label: TrustLabel
    reason: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/providers",
    response_model=list[ResearchProviderStatus],
    dependencies=[require_scope("tools:execute")],
)
async def list_search_providers(request: Request) -> list[ResearchProviderStatus]:
    """List all registered search providers with health/auth status."""
    return _get_registry(request).list_diagnostics()


@router.get(
    "/search",
    response_model=WebSearchResponse,
    dependencies=[require_scope("tools:execute")],
)
async def execute_search(
    request: Request,
    q: str = Query(..., min_length=1, description="Search query"),
    provider: str | None = Query(None, description="Provider ID filter"),
    limit: int = Query(10, ge=1, le=25, description="Max results"),
    all_providers: bool = Query(False, description="Query all providers"),
) -> WebSearchResponse:
    """Execute a web search with optional provider filter."""
    registry = _get_registry(request)

    try:
        if all_providers:
            results = await registry.search_all(q, limit=limit, categories="general")
            return WebSearchResponse(
                query=q,
                all_providers=True,
                results=results,
            )
        else:
            results = await registry.search(
                q, provider_id=provider, limit=limit, categories="general"
            )
            resolved_provider = provider or registry.default_provider_id
            return WebSearchResponse(
                query=q,
                provider_id=resolved_provider,
                results=results,
            )
    except ValueError as exc:
        message = str(exc)
        status_code = status.HTTP_400_BAD_REQUEST
        if "not configured" in message:
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        raise HTTPException(status_code=status_code, detail=message) from exc


@router.get(
    "/trust-domains",
    response_model=list[TrustedDomainEntry],
    dependencies=[require_scope("tools:execute")],
)
async def list_trust_domains(request: Request) -> list[TrustedDomainEntry]:
    """List the domain trust heuristic patterns used for result classification."""
    return _get_registry(request).get_trust_domain_entries()


@router.get(
    "/trust-classify",
    response_model=TrustClassificationResponse,
    dependencies=[require_scope("tools:execute")],
)
async def classify_domain(
    domain: str = Query(..., min_length=1, description="Domain to classify"),
) -> TrustClassificationResponse:
    """Classify a single domain's trust label."""
    label, reason = classify_domain_trust(domain)
    return TrustClassificationResponse(
        domain=domain,
        label=label,
        reason=reason,
    )
