"""Structured web research and provider diagnostics routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from agent33.security.permissions import require_scope
from agent33.web_research import (
    ProviderStatusInfo,
    ResearchFetchRequest,
    ResearchProviderStatus,
    ResearchSearchRequest,
    ResearchSearchResponse,
    WebFetchArtifact,
    WebResearchService,
)

router = APIRouter(prefix="/v1/research", tags=["research"])

_research_service: WebResearchService | None = None


def set_research_service(service: WebResearchService | None) -> None:
    """Set the module-level research service reference."""
    global _research_service  # noqa: PLW0603
    _research_service = service


def _get_research_service(request: Request) -> WebResearchService:
    if _research_service is not None:
        return _research_service
    svc: Any = getattr(request.app.state, "web_research_service", None)
    if svc is not None:
        return svc  # type: ignore[no-any-return]
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Web research service not initialized",
    )


@router.get(
    "/providers",
    response_model=list[ResearchProviderStatus],
    dependencies=[require_scope("tools:execute")],
)
async def list_research_providers(request: Request) -> list[ResearchProviderStatus]:
    """List configured research providers and their diagnostics."""
    return _get_research_service(request).list_providers()


@router.get(
    "/providers/status",
    response_model=list[ProviderStatusInfo],
    dependencies=[require_scope("agents:read")],
)
async def provider_status_summary(request: Request) -> list[ProviderStatusInfo]:
    """Return dashboard-friendly provider health summaries."""
    return _get_research_service(request).provider_status_summary()


@router.post(
    "/search",
    response_model=ResearchSearchResponse,
    dependencies=[require_scope("tools:execute")],
)
async def search_research(
    request: Request,
    body: ResearchSearchRequest,
) -> ResearchSearchResponse:
    """Run structured web research against the configured provider set."""
    service = _get_research_service(request)
    try:
        return await service.search(
            body.query,
            provider_id=body.provider,
            limit=body.limit,
            categories=body.categories,
        )
    except ValueError as exc:
        message = str(exc)
        status_code = status.HTTP_400_BAD_REQUEST
        if "not configured" in message:
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        raise HTTPException(status_code=status_code, detail=message) from exc


@router.post(
    "/fetch",
    response_model=WebFetchArtifact,
    dependencies=[require_scope("tools:execute")],
)
async def fetch_research(
    request: Request,
    body: ResearchFetchRequest,
) -> WebFetchArtifact:
    """Fetch a URL through the governed web research service."""
    service = _get_research_service(request)
    try:
        return await service.fetch(
            body.url,
            allowed_domains=body.allowed_domains,
            headers=body.headers,
            body=body.body,
            method=body.method,
            timeout=body.timeout,
        )
    except ValueError as exc:
        message = str(exc)
        status_code = status.HTTP_400_BAD_REQUEST
        if "not configured" in message:
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        raise HTTPException(status_code=status_code, detail=message) from exc
