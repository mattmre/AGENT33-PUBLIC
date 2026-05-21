"""Ollama setup UX routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from agent33.config import settings
from agent33.security.permissions import require_scope
from agent33.services.ollama_readiness import (
    OllamaModelsResponse,
    OllamaReadinessService,
    OllamaStatusResponse,
)

router = APIRouter(prefix="/v1/ollama", tags=["ollama"])


def get_ollama_readiness_service(request: Request) -> OllamaReadinessService:
    """Return the shared Ollama readiness service, creating it lazily."""

    svc: OllamaReadinessService | None = getattr(
        request.app.state,
        "ollama_readiness_service",
        None,
    )
    if svc is None:
        svc = OllamaReadinessService(settings=settings)
        request.app.state.ollama_readiness_service = svc
    return svc


OllamaReadinessDependency = Annotated[
    OllamaReadinessService,
    Depends(get_ollama_readiness_service),
]


@router.get(
    "/status",
    response_model=OllamaStatusResponse,
    dependencies=[require_scope("operator:read")],
)
async def ollama_status(
    svc: OllamaReadinessDependency,
    base_url: str | None = Query(default=None),
) -> OllamaStatusResponse:
    """Return Ollama reachability and local model availability."""

    return await svc.status(base_url=base_url)


@router.get(
    "/models",
    response_model=OllamaModelsResponse,
    dependencies=[require_scope("operator:read")],
)
async def ollama_models(
    svc: OllamaReadinessDependency,
    base_url: str | None = Query(default=None),
) -> OllamaModelsResponse:
    """Return available Ollama models for setup UI."""

    return await svc.models(base_url=base_url)
