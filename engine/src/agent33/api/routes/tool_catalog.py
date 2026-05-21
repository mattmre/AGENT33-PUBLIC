"""FastAPI router for the runtime tool catalog and schema lookup."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request, status

from agent33.api.routes.tenant_access import tenant_filter_for_request
from agent33.security.permissions import require_scope
from agent33.tools.catalog import (
    CatalogEntry,
    CatalogPage,
    CatalogSearchRequest,
    CategoryCount,
    ProviderCount,
    ToolCatalogService,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/v1/catalog", tags=["tool-catalog"])

# Module-level service reference (set during lifespan or tests)
_catalog_service: ToolCatalogService | None = None


def set_catalog_service(service: ToolCatalogService | None) -> None:
    """Set the module-level catalog service reference."""
    global _catalog_service  # noqa: PLW0603
    _catalog_service = service


def _get_catalog_service(request: Request) -> ToolCatalogService:
    """Resolve the catalog service from the test override or app state."""
    if _catalog_service is not None:
        return _catalog_service
    svc: Any = getattr(request.app.state, "tool_catalog_service", None)
    if svc is not None:
        return svc  # type: ignore[no-any-return]
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Tool catalog service not initialized",
    )


def _catalog_tenant_id(request: Request) -> str:
    tenant_filter = tenant_filter_for_request(request)
    return tenant_filter or ""


@router.get(
    "/tools",
    response_model=CatalogPage,
    dependencies=[require_scope("tools:execute")],
)
async def list_tools(
    request: Request,
    category: str | None = None,
    provider: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> CatalogPage:
    """Browse all tools in the catalog with optional filtering."""
    svc = _get_catalog_service(request)
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    tenant_id = _catalog_tenant_id(request)
    return svc.list_tools(
        category=category,
        provider=provider,
        search=search,
        limit=limit,
        offset=offset,
        tenant_id=tenant_id,
    )


@router.get(
    "/tools/{name}/schema",
    dependencies=[require_scope("tools:execute")],
)
async def get_tool_schema(request: Request, name: str) -> dict[str, Any]:
    """Get just the JSON Schema for a tool by name."""
    svc = _get_catalog_service(request)
    tenant_id = _catalog_tenant_id(request)
    entry = svc.get_tool(name, tenant_id=tenant_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool '{name}' not found in catalog",
        )
    if not entry.parameters_schema:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No JSON Schema available for tool '{name}'",
        )
    return entry.parameters_schema


@router.get(
    "/tools/{name}",
    response_model=CatalogEntry,
    dependencies=[require_scope("tools:execute")],
)
async def get_tool_detail(request: Request, name: str) -> CatalogEntry:
    """Get full detail for a single tool by name."""
    svc = _get_catalog_service(request)
    entry = svc.get_tool(name, tenant_id=_catalog_tenant_id(request))
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool '{name}' not found in catalog",
        )
    return entry


@router.get(
    "/categories",
    response_model=list[CategoryCount],
    dependencies=[require_scope("tools:execute")],
)
async def list_categories(request: Request) -> list[CategoryCount]:
    """List all tool categories with counts."""
    svc = _get_catalog_service(request)
    return svc.list_categories(tenant_id=_catalog_tenant_id(request))


@router.get(
    "/providers",
    response_model=list[ProviderCount],
    dependencies=[require_scope("tools:execute")],
)
async def list_providers(request: Request) -> list[ProviderCount]:
    """List all tool providers with counts."""
    svc = _get_catalog_service(request)
    return svc.list_providers(tenant_id=_catalog_tenant_id(request))


@router.post(
    "/search",
    response_model=CatalogPage,
    dependencies=[require_scope("tools:execute")],
)
async def search_catalog(
    request: Request,
    body: CatalogSearchRequest,
) -> CatalogPage:
    """Search across tools with multiple filter criteria."""
    svc = _get_catalog_service(request)
    return svc.search(body, tenant_id=_catalog_tenant_id(request))
