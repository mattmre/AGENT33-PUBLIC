"""OpenRouter catalog and setup UX routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from agent33.config import settings
from agent33.security.permissions import require_scope
from agent33.services.openrouter_catalog import (
    OpenRouterCatalogError,
    OpenRouterCatalogService,
    OpenRouterModelsResponse,
    OpenRouterProbeRequest,
    OpenRouterProbeResponse,
)

router = APIRouter(prefix="/v1/openrouter", tags=["openrouter"])


def get_openrouter_service(request: Request) -> OpenRouterCatalogService:
    """Return the shared OpenRouter catalog service, creating it lazily."""
    svc: OpenRouterCatalogService | None = getattr(request.app.state, "openrouter_service", None)
    if svc is None:
        svc = OpenRouterCatalogService(settings=settings)
        request.app.state.openrouter_service = svc
    return svc


OpenRouterServiceDependency = Annotated[OpenRouterCatalogService, Depends(get_openrouter_service)]


@router.get(
    "/models",
    response_model=OpenRouterModelsResponse,
    dependencies=[require_scope("operator:read")],
)
async def openrouter_models(svc: OpenRouterServiceDependency) -> OpenRouterModelsResponse:
    """Return a normalized OpenRouter model catalog for setup and search UX."""
    try:
        return await svc.list_models()
    except OpenRouterCatalogError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=exc.detail,
        ) from exc


@router.post(
    "/probe",
    response_model=OpenRouterProbeResponse,
    dependencies=[require_scope("operator:read")],
)
async def openrouter_probe(
    svc: OpenRouterServiceDependency,
    body: OpenRouterProbeRequest | None = None,
) -> OpenRouterProbeResponse:
    """Run public and authenticated OpenRouter connectivity checks."""
    return await svc.probe(body)
