"""FastAPI routes for the Phase 47 capability pack system.

Provides CRUD for capability packs and endpoints to apply/remove packs
to/from agent definitions.  All state is in-memory via the
CapabilityPackRegistry stored on ``app.state.capability_pack_registry``.
"""

# NOTE: no ``from __future__ import annotations`` -- Pydantic needs runtime
# types for request-body validation.

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from agent33.agents.capability_packs import (
    CapabilityPack,
    CapabilityPackRegistry,
    CompatibilityRequirements,
)
from agent33.agents.definition import AgentDefinition, SpecCapability
from agent33.agents.registry import AgentRegistry
from agent33.security.permissions import require_scope

logger = structlog.get_logger()

router = APIRouter(prefix="/v1/capability-packs", tags=["capability-packs"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CreatePackRequest(BaseModel):
    """Request body for creating a custom capability pack."""

    name: str = Field(
        ...,
        min_length=2,
        max_length=64,
        pattern=r"^[a-z][a-z0-9-]*$",
    )
    description: str = Field(default="", max_length=500)
    version: str = Field(..., pattern=r"^\d+\.\d+\.\d+$")
    capabilities: list[str] = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)
    author: str = Field(default="custom")
    compatibility: CompatibilityRequirements = Field(
        default_factory=CompatibilityRequirements,
    )


class UpdatePackRequest(BaseModel):
    """Request body for updating a custom capability pack."""

    description: str | None = Field(default=None, max_length=500)
    version: str | None = Field(default=None, pattern=r"^\d+\.\d+\.\d+$")
    capabilities: list[str] | None = Field(default=None, min_length=1)
    tags: list[str] | None = None
    author: str | None = None
    compatibility: CompatibilityRequirements | None = None


class ApplyPackRequest(BaseModel):
    """Request body for applying a pack to an agent."""

    agent_name: str = Field(..., min_length=2)
    skip_compat_check: bool = Field(default=False)


class RemovePackRequest(BaseModel):
    """Request body for removing a pack from an agent."""

    agent_name: str = Field(..., min_length=2)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_cap_pack_registry(request: Request) -> CapabilityPackRegistry:
    registry: CapabilityPackRegistry | None = getattr(
        request.app.state, "capability_pack_registry", None
    )
    if registry is None:
        raise HTTPException(
            status_code=503,
            detail="Capability pack registry not initialized",
        )
    return registry


def _get_agent_registry(request: Request) -> AgentRegistry:
    registry: AgentRegistry | None = getattr(request.app.state, "agent_registry", None)
    if registry is None:
        raise HTTPException(
            status_code=503,
            detail="Agent registry not initialized",
        )
    return registry


def _resolve_capabilities(raw: list[str]) -> list[SpecCapability]:
    """Convert raw string IDs to SpecCapability, raising on invalid."""
    result: list[SpecCapability] = []
    for cap_str in raw:
        try:
            result.append(SpecCapability(cap_str))
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid capability ID: '{cap_str}'. "
                f"Valid IDs: {[c.value for c in SpecCapability]}",
            ) from exc
    return result


def _get_agent_or_404(
    agent_registry: AgentRegistry,
    agent_name: str,
) -> AgentDefinition:
    agent = agent_registry.get(agent_name)
    if agent is None:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agent_name}' not found",
        )
    return agent


# ---------------------------------------------------------------------------
# Endpoints -- List / Search
# ---------------------------------------------------------------------------


@router.get("", dependencies=[require_scope("agents:read")])
async def list_capability_packs(
    request: Request,
    builtin_only: bool = Query(default=False, description="Only return built-in packs"),
    custom_only: bool = Query(default=False, description="Only return custom packs"),
) -> dict[str, Any]:
    """List all registered capability packs."""
    registry = _get_cap_pack_registry(request)

    if builtin_only:
        packs = registry.list_builtin()
    elif custom_only:
        packs = registry.list_custom()
    else:
        packs = registry.list_all()

    return {
        "packs": [registry.to_summary(p) for p in packs],
        "count": len(packs),
    }


@router.get("/search", dependencies=[require_scope("agents:read")])
async def search_capability_packs(
    request: Request,
    q: str = Query(..., min_length=1, description="Search query"),
) -> dict[str, Any]:
    """Search packs by name, description, or tags."""
    registry = _get_cap_pack_registry(request)
    results = registry.search(q)
    return {
        "results": [registry.to_summary(p) for p in results],
        "count": len(results),
        "query": q,
    }


# ---------------------------------------------------------------------------
# Endpoints -- Single pack detail
# ---------------------------------------------------------------------------


@router.get("/{name}", dependencies=[require_scope("agents:read")])
async def get_capability_pack(name: str, request: Request) -> dict[str, Any]:
    """Get full details of a capability pack."""
    registry = _get_cap_pack_registry(request)
    pack = registry.get(name)
    if pack is None:
        raise HTTPException(status_code=404, detail=f"Capability pack '{name}' not found")
    return registry.to_detail(pack)


# ---------------------------------------------------------------------------
# Endpoints -- Create / Update / Delete
# ---------------------------------------------------------------------------


@router.post("", status_code=201, dependencies=[require_scope("agents:write")])
async def create_capability_pack(
    body: CreatePackRequest,
    request: Request,
) -> dict[str, Any]:
    """Register a new custom capability pack."""
    registry = _get_cap_pack_registry(request)

    if body.name in registry:
        raise HTTPException(
            status_code=409,
            detail=f"Capability pack '{body.name}' already exists",
        )

    capabilities = _resolve_capabilities(body.capabilities)

    pack = CapabilityPack(
        name=body.name,
        description=body.description,
        version=body.version,
        capabilities=capabilities,
        tags=body.tags,
        author=body.author,
        compatibility=body.compatibility,
        builtin=False,
    )

    registry.register(pack)
    return registry.to_detail(pack)


@router.put("/{name}", dependencies=[require_scope("agents:write")])
async def update_capability_pack(
    name: str,
    body: UpdatePackRequest,
    request: Request,
) -> dict[str, Any]:
    """Update a custom capability pack (cannot update built-in packs)."""
    registry = _get_cap_pack_registry(request)
    existing = registry.get(name)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Capability pack '{name}' not found")

    if existing.builtin:
        raise HTTPException(
            status_code=403,
            detail=f"Cannot modify built-in pack '{name}'",
        )

    update_data: dict[str, Any] = {}
    if body.description is not None:
        update_data["description"] = body.description
    if body.version is not None:
        update_data["version"] = body.version
    if body.capabilities is not None:
        update_data["capabilities"] = _resolve_capabilities(body.capabilities)
    if body.tags is not None:
        update_data["tags"] = body.tags
    if body.author is not None:
        update_data["author"] = body.author
    if body.compatibility is not None:
        update_data["compatibility"] = body.compatibility

    updated = existing.model_copy(update=update_data)
    registry.register_force(updated)
    return registry.to_detail(updated)


@router.delete(
    "/{name}",
    status_code=204,
    response_model=None,
    dependencies=[require_scope("agents:write")],
)
async def delete_capability_pack(
    name: str,
    request: Request,
    force: bool = Query(default=False, description="Force-delete even built-in packs"),
) -> None:
    """Delete a capability pack."""
    registry = _get_cap_pack_registry(request)

    pack = registry.get(name)
    if pack is None:
        raise HTTPException(status_code=404, detail=f"Capability pack '{name}' not found")

    try:
        removed = registry.unregister(name, force=force)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    if not removed:
        raise HTTPException(status_code=404, detail=f"Capability pack '{name}' not found")


# ---------------------------------------------------------------------------
# Endpoints -- Apply / Remove / Compatibility
# ---------------------------------------------------------------------------


@router.post(
    "/{name}/check-compatibility",
    dependencies=[require_scope("agents:read")],
)
async def check_pack_compatibility(
    name: str,
    body: ApplyPackRequest,
    request: Request,
) -> dict[str, Any]:
    """Check if a pack is compatible with an agent without applying it."""
    cap_registry = _get_cap_pack_registry(request)
    agent_registry = _get_agent_registry(request)
    agent = _get_agent_or_404(agent_registry, body.agent_name)

    result = cap_registry.check_compatibility(name, agent)
    return result.model_dump()


@router.post("/{name}/apply", dependencies=[require_scope("agents:write")])
async def apply_capability_pack(
    name: str,
    body: ApplyPackRequest,
    request: Request,
) -> dict[str, Any]:
    """Apply a capability pack to an agent, augmenting its capabilities."""
    cap_registry = _get_cap_pack_registry(request)
    agent_registry = _get_agent_registry(request)
    agent = _get_agent_or_404(agent_registry, body.agent_name)

    result = cap_registry.apply_pack(
        name,
        agent,
        skip_compat_check=body.skip_compat_check,
    )

    if not result.success:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"Failed to apply pack '{name}' to agent '{body.agent_name}'",
                "errors": result.errors,
                "warnings": result.warnings,
            },
        )

    return result.model_dump()


@router.post("/{name}/remove", dependencies=[require_scope("agents:write")])
async def remove_capability_pack(
    name: str,
    body: RemovePackRequest,
    request: Request,
) -> dict[str, Any]:
    """Remove a capability pack from an agent."""
    cap_registry = _get_cap_pack_registry(request)
    agent_registry = _get_agent_registry(request)
    agent = _get_agent_or_404(agent_registry, body.agent_name)

    result = cap_registry.remove_pack(name, agent)

    if not result.success:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"Failed to remove pack '{name}' from agent '{body.agent_name}'",
                "errors": result.errors,
                "warnings": result.warnings,
            },
        )

    return result.model_dump()


@router.get(
    "/{name}/agents",
    dependencies=[require_scope("agents:read")],
)
async def list_pack_agents(name: str, request: Request) -> dict[str, Any]:
    """List agents that have a specific pack applied."""
    cap_registry = _get_cap_pack_registry(request)
    pack = cap_registry.get(name)
    if pack is None:
        raise HTTPException(status_code=404, detail=f"Capability pack '{name}' not found")

    agents = cap_registry.get_pack_agents(name)
    return {
        "pack_name": name,
        "agents": agents,
        "count": len(agents),
    }


@router.get(
    "/agents/{agent_name}/packs",
    dependencies=[require_scope("agents:read")],
)
async def list_agent_packs(agent_name: str, request: Request) -> dict[str, Any]:
    """List capability packs applied to a specific agent."""
    cap_registry = _get_cap_pack_registry(request)
    agent_registry = _get_agent_registry(request)

    # Verify the agent exists
    _get_agent_or_404(agent_registry, agent_name)

    pack_names = cap_registry.get_agent_packs(agent_name)
    packs = [cap_registry.get(n) for n in pack_names]
    return {
        "agent_name": agent_name,
        "packs": [cap_registry.to_summary(p) for p in packs if p is not None],
        "count": len(pack_names),
    }
