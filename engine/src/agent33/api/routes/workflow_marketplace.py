"""FastAPI router for the workflow template marketplace.

Provides endpoints for browsing, searching, installing, and rating
workflow templates.
"""

from __future__ import annotations

import contextlib
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from agent33.security.permissions import require_scope
from agent33.workflows.marketplace import (
    TemplateCategory,
    TemplateRating,
    TemplateSearchQuery,
    TemplateSortField,
    WorkflowMarketplace,
    WorkflowTemplate,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/v1/workflow-marketplace", tags=["workflow-marketplace"])

# Module-level singleton; set during lifespan or tests.
_marketplace: WorkflowMarketplace | None = None


def set_workflow_marketplace(marketplace: WorkflowMarketplace) -> None:
    """Register the shared workflow marketplace instance."""
    global _marketplace
    _marketplace = marketplace


def get_workflow_marketplace(request: Request | None = None) -> WorkflowMarketplace:
    """Return the current marketplace, checking app.state first, then module-level."""
    if request is not None:
        mp: WorkflowMarketplace | None = getattr(request.app.state, "workflow_marketplace", None)
        if mp is not None:
            return mp
    if _marketplace is not None:
        return _marketplace
    raise HTTPException(
        status_code=503,
        detail="Workflow marketplace not initialized",
    )


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class TemplateCreateRequest(BaseModel):
    """Request body for publishing a new template."""

    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)
    category: TemplateCategory = TemplateCategory.CUSTOM
    tags: list[str] = Field(default_factory=list)
    version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    author: str = Field(default="", max_length=128)
    template_definition: dict[str, Any] = Field(default_factory=dict)


class TemplateRateRequest(BaseModel):
    """Request body for rating a template."""

    stars: int = Field(..., ge=1, le=5)
    comment: str = Field(default="", max_length=1000)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/templates", dependencies=[require_scope("workflows:read")])
async def list_templates(
    request: Request,
    q: str | None = Query(default=None, description="Search query string"),
    category: str | None = Query(default=None, description="Category filter"),
    tags: str | None = Query(
        default=None, description="Comma-separated tag filter (all must match)"
    ),
    sort_by: str | None = Query(default=None, description="Sort field"),
    limit: int = Query(default=50, ge=1, le=200, description="Results per page"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
) -> dict[str, Any]:
    """List or search workflow templates in the marketplace."""
    mp = get_workflow_marketplace(request)

    # Parse enum query params
    resolved_category: TemplateCategory | None = None
    if category is not None:
        with contextlib.suppress(ValueError):
            resolved_category = TemplateCategory(category)

    resolved_sort = TemplateSortField.NAME
    if sort_by is not None:
        with contextlib.suppress(ValueError):
            resolved_sort = TemplateSortField(sort_by)

    # If a search query or tags are provided, use search; otherwise use list
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    if q or tag_list or resolved_category or resolved_sort != TemplateSortField.NAME:
        search_query = TemplateSearchQuery(
            query=q or "",
            category=resolved_category,
            tags=tag_list,
            sort_by=resolved_sort,
            limit=limit,
            offset=offset,
        )
        results = mp.search_templates(search_query)
    else:
        results = mp.list_templates(category=resolved_category, limit=limit, offset=offset)

    return {
        "templates": [t.model_dump(mode="json") for t in results],
        "count": len(results),
        "total": mp.count,
    }


@router.get("/templates/{template_id}", dependencies=[require_scope("workflows:read")])
async def get_template(template_id: str, request: Request) -> dict[str, Any]:
    """Get a single template by ID."""
    mp = get_workflow_marketplace(request)
    template = mp.get_template(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
    return template.model_dump(mode="json")


@router.post("/templates", status_code=201, dependencies=[require_scope("workflows:write")])
async def publish_template(body: TemplateCreateRequest, request: Request) -> dict[str, Any]:
    """Publish a new workflow template to the marketplace."""
    mp = get_workflow_marketplace(request)

    template = WorkflowTemplate(
        name=body.name,
        description=body.description,
        category=body.category,
        tags=body.tags,
        version=body.version,
        author=body.author,
        template_definition=body.template_definition,
    )

    try:
        template_id = mp.register_template(template)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "workflow_template_published",
        template_id=template_id,
        name=body.name,
    )

    return {
        "template_id": template_id,
        "name": body.name,
        "created": True,
    }


@router.post(
    "/templates/{template_id}/install",
    dependencies=[require_scope("workflows:write")],
)
async def install_template(template_id: str, request: Request) -> dict[str, Any]:
    """Install a marketplace template into the live workflow registry."""
    mp = get_workflow_marketplace(request)

    # Resolve tenant from auth context
    user = getattr(request.state, "user", None)
    tenant_id = getattr(user, "tenant_id", "") if user is not None else ""

    try:
        result = mp.install_template(template_id, tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    logger.info(
        "workflow_template_installed",
        template_id=template_id,
        tenant_id=tenant_id,
        workflow_name=result.workflow_name,
    )

    return result.model_dump(mode="json")


@router.post(
    "/templates/{template_id}/rate",
    dependencies=[require_scope("workflows:write")],
)
async def rate_template(
    template_id: str, body: TemplateRateRequest, request: Request
) -> dict[str, Any]:
    """Rate a marketplace template (1-5 stars)."""
    mp = get_workflow_marketplace(request)

    user = getattr(request.state, "user", None)
    tenant_id = getattr(user, "tenant_id", "") if user is not None else ""

    rating = TemplateRating(
        template_id=template_id,
        tenant_id=tenant_id,
        stars=body.stars,
        comment=body.comment,
    )

    try:
        mp.rate_template(template_id, rating)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Retrieve updated template to return current rating
    template = mp.get_template(template_id)
    current_rating = template.rating if template else 0.0
    rating_count = template.rating_count if template else 0

    logger.info(
        "workflow_template_rated",
        template_id=template_id,
        stars=body.stars,
        tenant_id=tenant_id,
    )

    return {
        "template_id": template_id,
        "stars": body.stars,
        "current_rating": current_rating,
        "rating_count": rating_count,
    }


@router.get("/stats", dependencies=[require_scope("workflows:read")])
async def get_marketplace_stats(request: Request) -> dict[str, Any]:
    """Get marketplace statistics."""
    mp = get_workflow_marketplace(request)
    return mp.get_template_stats()


@router.delete(
    "/templates/{template_id}",
    dependencies=[require_scope("workflows:write")],
)
async def delete_template(template_id: str, request: Request) -> dict[str, Any]:
    """Remove a template from the marketplace."""
    mp = get_workflow_marketplace(request)
    removed = mp.remove_template(template_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

    logger.info("workflow_template_deleted", template_id=template_id)
    return {"template_id": template_id, "deleted": True}
