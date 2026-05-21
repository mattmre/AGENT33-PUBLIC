"""LM Studio setup UX routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from agent33.config import settings
from agent33.security.permissions import require_scope
from agent33.services.lm_studio_readiness import (
    LMStudioModelsResponse,
    LMStudioReadinessService,
    LMStudioStatusResponse,
)

router = APIRouter(prefix="/v1/lm-studio", tags=["lm-studio"])


def get_lm_studio_readiness_service(request: Request) -> LMStudioReadinessService:
    """Return the shared LM Studio readiness service, creating it lazily."""

    svc: LMStudioReadinessService | None = getattr(
        request.app.state,
        "lm_studio_readiness_service",
        None,
    )
    if svc is None:
        svc = LMStudioReadinessService(settings=settings)
        request.app.state.lm_studio_readiness_service = svc
    return svc


LMStudioReadinessDependency = Annotated[
    LMStudioReadinessService,
    Depends(get_lm_studio_readiness_service),
]


@router.get(
    "/status",
    response_model=LMStudioStatusResponse,
    dependencies=[require_scope("operator:read")],
)
async def lm_studio_status(
    svc: LMStudioReadinessDependency,
    base_url: str | None = Query(default=None),
) -> LMStudioStatusResponse:
    """Return LM Studio reachability and local model availability."""

    return await svc.status(base_url=base_url)


@router.get(
    "/models",
    response_model=LMStudioModelsResponse,
    dependencies=[require_scope("operator:read")],
)
async def lm_studio_models(
    svc: LMStudioReadinessDependency,
    base_url: str | None = Query(default=None),
) -> LMStudioModelsResponse:
    """Return available LM Studio models for setup UI."""

    return await svc.models(base_url=base_url)
