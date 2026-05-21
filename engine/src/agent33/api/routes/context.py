"""Context engine API endpoints (Track 8).

Provides status, assembly, and health for the pluggable context engine.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from agent33.security.permissions import require_scope

router = APIRouter(prefix="/v1/context", tags=["context"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level service accessor
# ---------------------------------------------------------------------------

_context_engine_registry: Any = None


def set_context_engine_registry(registry: Any) -> None:
    """Set the context engine registry (called from lifespan)."""
    global _context_engine_registry  # noqa: PLW0603
    _context_engine_registry = registry


def _get_registry(request: Request) -> Any:
    """Extract context engine registry from app state or module-level fallback."""
    if hasattr(request.app.state, "context_engine_registry"):
        reg = request.app.state.context_engine_registry
    else:
        reg = _context_engine_registry
    if reg is None:
        raise HTTPException(status_code=503, detail="Context engine registry not initialized")
    return reg


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ContextStatusResponse(BaseModel):
    """Response for GET /v1/context/status."""

    active_engine: str = ""
    available_engines: list[str] = Field(default_factory=list)


class ContextAssemblyResponse(BaseModel):
    """Response for GET /v1/context/{session_id}/assembly."""

    session_id: str
    engine_id: str = ""
    total_tokens: int = 0
    slots_count: int = 0
    compaction_triggered: bool = False
    slots: list[dict[str, Any]] = Field(default_factory=list)


class ContextHealthResponse(BaseModel):
    """Response for GET /v1/context/health."""

    active_engine: str = ""
    engines: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/status", dependencies=[require_scope("sessions:read")])
async def context_status(request: Request) -> ContextStatusResponse:
    """Return active context engine and available alternatives."""
    registry = _get_registry(request)
    active = registry.get_active()
    return ContextStatusResponse(
        active_engine=active.engine_id,
        available_engines=registry.list_available(),
    )


@router.get("/{session_id}/assembly", dependencies=[require_scope("sessions:read")])
async def context_assembly(session_id: str, request: Request) -> ContextAssemblyResponse:
    """Return the latest assembly report for a session."""
    registry = _get_registry(request)
    engine = registry.get_active()
    report = await engine.assemble(session_id)
    return ContextAssemblyResponse(
        session_id=report.session_id,
        engine_id=report.engine_id,
        total_tokens=report.total_tokens,
        slots_count=len(report.slots_filled),
        compaction_triggered=report.compaction_triggered,
        slots=[slot.model_dump() for slot in report.slots_filled],
    )


@router.get("/health", dependencies=[require_scope("sessions:read")])
async def context_health(request: Request) -> ContextHealthResponse:
    """Return context provider health across all registered engines."""
    registry = _get_registry(request)
    health_data = registry.health_check()
    return ContextHealthResponse(
        active_engine=health_data.get("active_engine", ""),
        engines=health_data.get("engines", {}),
    )
