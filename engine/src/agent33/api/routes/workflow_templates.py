"""FastAPI router for the workflow template catalog.

Provides read-only access to canonical workflow templates discovered from
the ``core/workflows/`` directory tree.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query

from agent33.security.permissions import require_scope
from agent33.workflows.template_catalog import TemplateCatalog  # noqa: TCH001

logger = structlog.get_logger()

router = APIRouter(prefix="/v1/workflows/templates", tags=["workflow-templates"])

# Module-level singleton; set during lifespan or tests.
_catalog: TemplateCatalog | None = None


def set_template_catalog(catalog: TemplateCatalog) -> None:
    """Register the shared template catalog instance."""
    global _catalog
    _catalog = catalog


def get_template_catalog() -> TemplateCatalog:
    """Return the current catalog, raising if uninitialized."""
    if _catalog is None:
        raise HTTPException(
            status_code=503,
            detail="Template catalog not initialized",
        )
    return _catalog


@router.get("/", dependencies=[require_scope("workflows:read")])
async def list_templates(
    tags: str | None = Query(default=None, description="Comma-separated tag filter"),
    limit: int | None = Query(default=None, ge=1, le=100),
) -> dict[str, Any]:
    """List all canonical workflow templates."""
    catalog = get_template_catalog()
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    templates = catalog.list_templates(tags=tag_list, limit=limit)
    return {"templates": [t.model_dump(mode="json") for t in templates]}


@router.get("/{template_id}", dependencies=[require_scope("workflows:read")])
async def get_template(template_id: str) -> dict[str, Any]:
    """Get a single template summary by ID."""
    catalog = get_template_catalog()
    template = catalog.get_template(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
    return template.model_dump(mode="json")


@router.get("/{template_id}/schema", dependencies=[require_scope("workflows:read")])
async def get_template_schema(template_id: str) -> dict[str, Any]:
    """Get the input/output schema for a template."""
    catalog = get_template_catalog()
    schema = catalog.get_schema(template_id)
    if schema is None:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
    return schema.model_dump(mode="json")


@router.get("/{template_id}/definition", dependencies=[require_scope("workflows:read")])
async def get_template_definition(template_id: str) -> dict[str, Any]:
    """Get the full workflow definition for a template (for registration)."""
    catalog = get_template_catalog()
    defn = catalog.get_definition_dict(template_id)
    if defn is None:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
    return defn


@router.get("/{template_id}/sample", dependencies=[require_scope("workflows:read")])
async def get_template_sample(template_id: str) -> dict[str, Any]:
    """Return sample inputs for a template (for 'try with sample data' mode)."""
    catalog = get_template_catalog()
    summary = catalog.get_template(template_id)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
    if not summary.sample_inputs:
        raise HTTPException(
            status_code=404, detail=f"Template '{template_id}' has no sample inputs"
        )
    return summary.sample_inputs


@router.post("/refresh", dependencies=[require_scope("workflows:write")])
async def refresh_templates() -> dict[str, Any]:
    """Re-scan the template directory and reload the catalog."""
    catalog = get_template_catalog()
    count = catalog.refresh()
    logger.info("template_catalog_refresh_requested", count=count)
    return {"refreshed": True, "template_count": count}
