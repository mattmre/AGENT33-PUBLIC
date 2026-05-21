"""FastAPI routes for Phase 46 discovery and resolution primitives."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status

from agent33.api.routes.tenant_access import tenant_filter_for_request
from agent33.discovery.service import (
    DiscoveryService,
    SkillDiscoveryResponse,
    ToolDiscoveryResponse,
    WorkflowResolutionResponse,
)
from agent33.security.permissions import require_scope

router = APIRouter(prefix="/v1/discovery", tags=["discovery"])

_discovery_service: DiscoveryService | None = None


def set_discovery_service(service: DiscoveryService | None) -> None:
    """Set the module-level discovery service reference."""
    global _discovery_service  # noqa: PLW0603
    _discovery_service = service


def _get_discovery_service(request: Request) -> DiscoveryService:
    """Resolve the discovery service from the test override or app state."""
    if _discovery_service is not None:
        return _discovery_service

    service = getattr(request.app.state, "discovery_service", None)
    if service is not None:
        return service  # type: ignore[no-any-return]

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Discovery service not initialized",
    )


@router.get(
    "/tools",
    response_model=ToolDiscoveryResponse,
    dependencies=[require_scope("tools:execute")],
)
async def discover_tools(
    request: Request,
    q: str = Query(..., min_length=1, description="Task or search query"),
    limit: int = Query(default=10, ge=1, le=50),
) -> ToolDiscoveryResponse:
    """Discover relevant runtime tools for a task."""
    service = _get_discovery_service(request)
    return ToolDiscoveryResponse(query=q, matches=service.discover_tools(q, limit=limit))


@router.get(
    "/skills",
    response_model=SkillDiscoveryResponse,
    dependencies=[require_scope("agents:read")],
)
async def discover_skills(
    request: Request,
    q: str = Query(..., min_length=1, description="Task or search query"),
    limit: int = Query(default=10, ge=1, le=50),
) -> SkillDiscoveryResponse:
    """Discover relevant skills while respecting tenant-enabled packs."""
    service = _get_discovery_service(request)
    tenant_id = tenant_filter_for_request(request)
    return SkillDiscoveryResponse(
        query=q,
        matches=service.discover_skills(q, limit=limit, tenant_id=tenant_id),
    )


@router.get(
    "/workflows/resolve",
    response_model=WorkflowResolutionResponse,
    dependencies=[require_scope("workflows:read")],
)
async def resolve_workflow(
    request: Request,
    q: str = Query(..., min_length=1, description="Task or search query"),
    limit: int = Query(default=10, ge=1, le=50),
) -> WorkflowResolutionResponse:
    """Resolve a workflow or canonical template for a task."""
    service = _get_discovery_service(request)
    tenant_id = tenant_filter_for_request(request)
    return WorkflowResolutionResponse(
        query=q,
        matches=service.resolve_workflow(q, limit=limit, tenant_id=tenant_id),
    )
