"""Unified model health setup UX routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, Query, Request

from agent33.api.routes.lm_studio import get_lm_studio_readiness_service
from agent33.api.routes.ollama import get_ollama_readiness_service
from agent33.config import settings
from agent33.security.permissions import require_scope
from agent33.services.model_health import (
    JudgmentPanelRequest,
    JudgmentPanelResponse,
    LocalOrchestrationReadinessService,
    ModelHealthService,
    TaskModelRoutingRequest,
    TaskModelRoutingResponse,
    UnifiedModelHealthResponse,
    build_judgment_panel,
    recommend_model_for_task,
)

if TYPE_CHECKING:
    from agent33.services.lm_studio_readiness import LMStudioReadinessService
    from agent33.services.ollama_readiness import OllamaReadinessService
else:
    LMStudioReadinessService = Any
    OllamaReadinessService = Any

router = APIRouter(prefix="/v1/model-health", tags=["model-health"])


def get_model_health_service(
    ollama_service: Annotated[
        OllamaReadinessService,
        Depends(get_ollama_readiness_service),
    ],
    lm_studio_service: Annotated[
        LMStudioReadinessService,
        Depends(get_lm_studio_readiness_service),
    ],
    local_orchestration_service: Annotated[
        LocalOrchestrationReadinessService,
        Depends(get_local_orchestration_readiness_service),
    ],
) -> ModelHealthService:
    """Return a request-local aggregate over shared readiness services."""

    return ModelHealthService(
        ollama_service=ollama_service,
        lm_studio_service=lm_studio_service,
        local_orchestration_service=local_orchestration_service,
    )


def get_local_orchestration_readiness_service(
    request: Request,
) -> LocalOrchestrationReadinessService:
    """Return the shared local orchestration readiness service, creating it lazily."""

    svc: LocalOrchestrationReadinessService | None = getattr(
        request.app.state,
        "local_orchestration_readiness_service",
        None,
    )
    if svc is None:
        svc = LocalOrchestrationReadinessService(settings=settings)
        request.app.state.local_orchestration_readiness_service = svc
    return svc


ModelHealthDependency = Annotated[
    ModelHealthService,
    Depends(get_model_health_service),
]


@router.get(
    "",
    response_model=UnifiedModelHealthResponse,
    dependencies=[require_scope("operator:read")],
)
async def local_model_health(
    svc: ModelHealthDependency,
    ollama_base_url: str | None = Query(default=None),
    lm_studio_base_url: str | None = Query(default=None),
    local_orchestration_base_url: str | None = Query(default=None),
) -> UnifiedModelHealthResponse:
    """Return combined Ollama, LM Studio, and local orchestration readiness for setup UI."""

    return await svc.status(
        ollama_base_url=ollama_base_url,
        lm_studio_base_url=lm_studio_base_url,
        local_orchestration_base_url=local_orchestration_base_url,
    )


@router.post(
    "/task-routing",
    response_model=TaskModelRoutingResponse,
    dependencies=[require_scope("operator:read")],
)
async def task_model_routing(
    body: TaskModelRoutingRequest,
    svc: ModelHealthDependency,
) -> TaskModelRoutingResponse:
    """Return an auditable task-to-model recommendation from current readiness."""
    return recommend_model_for_task(body, await svc.status())


@router.post(
    "/judgment-panel",
    response_model=JudgmentPanelResponse,
    dependencies=[require_scope("operator:read")],
)
async def judgment_panel(
    body: JudgmentPanelRequest,
    svc: ModelHealthDependency,
) -> JudgmentPanelResponse:
    """Return readiness-gated multi-model judgment for a high-impact proposal."""
    return build_judgment_panel(body, await svc.status())
