"""Hook management API endpoints (CRUD, diagnostics, testing)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from agent33.hooks.models import HookDefinition, HookEventType
from agent33.security.permissions import _get_token_payload, require_scope

if TYPE_CHECKING:
    from agent33.hooks.registry import HookRegistry

router = APIRouter(prefix="/v1/hooks", tags=["hooks"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class HookCreateRequest(BaseModel):
    """Body for creating a new hook definition."""

    name: str
    description: str = ""
    event_type: HookEventType
    priority: int = Field(default=100, ge=0, le=1000)
    handler_ref: str
    timeout_ms: float = Field(default=200.0, gt=0, le=5000)
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)
    fail_mode: Literal["open", "closed"] = "open"
    tags: list[str] = Field(default_factory=list)


class HookUpdateRequest(BaseModel):
    """Body for updating a hook definition."""

    name: str | None = None
    description: str | None = None
    priority: int | None = Field(default=None, ge=0, le=1000)
    timeout_ms: float | None = Field(default=None, gt=0, le=5000)
    enabled: bool | None = None
    config: dict[str, Any] | None = None
    fail_mode: Literal["open", "closed"] | None = None
    tags: list[str] | None = None


class HookResponse(BaseModel):
    """Response representing a hook definition."""

    hook_id: str
    name: str
    description: str
    event_type: str
    priority: int
    handler_ref: str
    timeout_ms: float
    enabled: bool
    tenant_id: str
    config: dict[str, Any]
    fail_mode: str
    tags: list[str]
    created_at: datetime
    updated_at: datetime


class HookToggleRequest(BaseModel):
    """Body for toggling a hook's enabled state."""

    enabled: bool


class HookTestRequest(BaseModel):
    """Body for dry-run testing a hook."""

    sample_context: dict[str, Any] = Field(default_factory=dict)


class HookTestResponse(BaseModel):
    """Response from a hook dry-run test."""

    hook_id: str
    hook_name: str
    success: bool
    error: str = ""
    context_after: dict[str, Any] = Field(default_factory=dict)


class HookStatsResponse(BaseModel):
    """Aggregate hook execution statistics."""

    total_hooks: int
    total_definitions: int
    by_event_type: dict[str, int]
    event_types_active: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_hook_registry(request: Request) -> HookRegistry:
    """Extract hook registry from app state."""
    registry: HookRegistry | None = getattr(request.app.state, "hook_registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="Hook registry not initialized")
    return registry


def _definition_to_response(defn: HookDefinition) -> HookResponse:
    return HookResponse(
        hook_id=defn.hook_id,
        name=defn.name,
        description=defn.description,
        event_type=defn.event_type.value,
        priority=defn.priority,
        handler_ref=defn.handler_ref,
        timeout_ms=defn.timeout_ms,
        enabled=defn.enabled,
        tenant_id=defn.tenant_id,
        config=defn.config,
        fail_mode=defn.fail_mode,
        tags=defn.tags,
        created_at=defn.created_at,
        updated_at=defn.updated_at,
    )


# ---------------------------------------------------------------------------
# CRUD Endpoints
# ---------------------------------------------------------------------------


@router.post("/", status_code=201, dependencies=[require_scope("hooks:manage")])
async def create_hook(
    body: HookCreateRequest,
    request: Request,
) -> HookResponse:
    """Create a new hook definition."""
    registry = _get_hook_registry(request)
    token_payload = _get_token_payload(request)
    tenant_id = token_payload.tenant_id or ""

    defn = HookDefinition(
        name=body.name,
        description=body.description,
        event_type=body.event_type,
        priority=body.priority,
        handler_ref=body.handler_ref,
        timeout_ms=body.timeout_ms,
        enabled=body.enabled,
        tenant_id=tenant_id,
        config=body.config,
        fail_mode=body.fail_mode,
        tags=body.tags,
    )

    # Resolve handler to validate it exists
    handler_cls = registry.resolve_handler(body.handler_ref)
    if handler_cls is None:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot resolve handler_ref: {body.handler_ref}",
        )

    # Instantiate and register
    try:
        if callable(handler_cls):
            hook_instance = handler_cls()
            # Override properties from definition
            if hasattr(hook_instance, "_name"):
                hook_instance._name = defn.name  # noqa: SLF001
            if hasattr(hook_instance, "_event_type"):
                hook_instance._event_type = defn.event_type.value  # noqa: SLF001
            if hasattr(hook_instance, "_priority"):
                hook_instance._priority = defn.priority  # noqa: SLF001
            if hasattr(hook_instance, "_enabled"):
                hook_instance._enabled = defn.enabled  # noqa: SLF001
            if hasattr(hook_instance, "_tenant_id"):
                hook_instance._tenant_id = defn.tenant_id  # noqa: SLF001
        else:
            raise TypeError(f"handler_ref resolved to non-callable: {type(handler_cls)}")
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Failed to instantiate handler: {exc}",
        ) from exc

    try:
        registry.register(hook_instance, defn)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return _definition_to_response(defn)


@router.get("/", dependencies=[require_scope("hooks:read")])
async def list_hooks(
    request: Request,
    event_type: str | None = Query(default=None, description="Filter by event type"),
    tenant_id: str | None = Query(default=None, description="Filter by tenant"),
    enabled: bool | None = Query(default=None, description="Filter by enabled state"),
) -> list[HookResponse]:
    """List all hook definitions with optional filtering."""
    registry = _get_hook_registry(request)
    definitions = registry.list_definitions(
        event_type=event_type,
        tenant_id=tenant_id,
        enabled=enabled,
    )
    return [_definition_to_response(d) for d in definitions]


@router.get("/stats", dependencies=[require_scope("hooks:read")])
async def hook_stats(request: Request) -> HookStatsResponse:
    """Return aggregate hook execution statistics."""
    registry = _get_hook_registry(request)
    stats = registry.stats()
    return HookStatsResponse(**stats)


@router.get("/{hook_id}", dependencies=[require_scope("hooks:read")])
async def get_hook(hook_id: str, request: Request) -> HookResponse:
    """Get a specific hook definition by ID."""
    registry = _get_hook_registry(request)
    defn = registry.get_definition(hook_id)
    if defn is None:
        raise HTTPException(status_code=404, detail=f"Hook '{hook_id}' not found")
    return _definition_to_response(defn)


@router.put("/{hook_id}", dependencies=[require_scope("hooks:manage")])
async def update_hook(
    hook_id: str,
    body: HookUpdateRequest,
    request: Request,
) -> HookResponse:
    """Update a hook definition."""
    registry = _get_hook_registry(request)

    updates: dict[str, Any] = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.description is not None:
        updates["description"] = body.description
    if body.priority is not None:
        updates["priority"] = body.priority
    if body.timeout_ms is not None:
        updates["timeout_ms"] = body.timeout_ms
    if body.enabled is not None:
        updates["enabled"] = body.enabled
    if body.config is not None:
        updates["config"] = body.config
    if body.fail_mode is not None:
        updates["fail_mode"] = body.fail_mode
    if body.tags is not None:
        updates["tags"] = body.tags
    updates["updated_at"] = datetime.now(UTC)

    defn = registry.update_definition(hook_id, updates)
    if defn is None:
        raise HTTPException(status_code=404, detail=f"Hook '{hook_id}' not found")
    return _definition_to_response(defn)


@router.delete("/{hook_id}", dependencies=[require_scope("hooks:manage")])
async def delete_hook(hook_id: str, request: Request) -> dict[str, str]:
    """Delete a hook definition."""
    registry = _get_hook_registry(request)
    if not registry.delete_definition(hook_id):
        raise HTTPException(status_code=404, detail=f"Hook '{hook_id}' not found")
    return {"status": "deleted", "hook_id": hook_id}


@router.put("/{hook_id}/toggle", dependencies=[require_scope("hooks:manage")])
async def toggle_hook(
    hook_id: str,
    body: HookToggleRequest,
    request: Request,
) -> HookResponse:
    """Toggle a hook's enabled/disabled state."""
    registry = _get_hook_registry(request)
    defn = registry.toggle(hook_id, body.enabled)
    if defn is None:
        raise HTTPException(status_code=404, detail=f"Hook '{hook_id}' not found")
    return _definition_to_response(defn)


@router.post("/{hook_id}/test", dependencies=[require_scope("hooks:manage")])
async def test_hook(
    hook_id: str,
    body: HookTestRequest,
    request: Request,
) -> HookTestResponse:
    """Dry-run a hook with sample context to verify it works."""
    from agent33.hooks.models import HookContext

    registry = _get_hook_registry(request)
    defn = registry.get_definition(hook_id)
    if defn is None:
        raise HTTPException(status_code=404, detail=f"Hook '{hook_id}' not found")

    # Find the registered hook instance
    hooks = registry.get_hooks(defn.event_type.value, defn.tenant_id)
    target_hook = None
    for h in hooks:
        if h.name == defn.name:
            target_hook = h
            break

    if target_hook is None:
        raise HTTPException(
            status_code=404,
            detail=f"Hook instance for '{defn.name}' not found in runtime",
        )

    # Build a test context
    test_ctx = HookContext(
        event_type=defn.event_type.value,
        tenant_id=defn.tenant_id,
        metadata=body.sample_context,
    )

    async def noop_next(ctx: HookContext) -> HookContext:
        return ctx

    try:
        result_ctx = await target_hook.execute(test_ctx, noop_next)
        return HookTestResponse(
            hook_id=hook_id,
            hook_name=defn.name,
            success=True,
            context_after=result_ctx.metadata,
        )
    except Exception as exc:
        return HookTestResponse(
            hook_id=hook_id,
            hook_name=defn.name,
            success=False,
            error=str(exc),
        )
