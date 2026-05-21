"""Delegation API endpoints (Phase 53).

Exposes the DelegationManager via REST so callers can:
  - Delegate a task to a named agent or by required capability.
  - Fan out multiple tasks in parallel.
  - Match capabilities to discover suitable agents.
  - Split a parent's token budget across N children.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from agent33.agents.delegation import (
    CapabilityMatch,
    DelegationManager,
    DelegationRequest,
    DelegationResult,
)
from agent33.security.permissions import require_scope

router = APIRouter(prefix="/v1/delegation", tags=["delegation"])
logger = logging.getLogger(__name__)


# -- dependency helpers ---------------------------------------------------


def _get_delegation_manager(request: Request) -> DelegationManager:
    """Resolve DelegationManager from app state or raise 503."""
    manager: DelegationManager | None = getattr(request.app.state, "delegation_manager", None)
    if manager is None:
        raise HTTPException(
            status_code=503,
            detail="DelegationManager not initialized",
        )
    return manager


# -- request / response models -------------------------------------------


class DelegateRequestBody(BaseModel):
    """Body for the single-delegation endpoint."""

    parent_agent: str = ""
    target_agent: str | None = None
    required_capability: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    token_budget: int = Field(default=4096, ge=100, le=200000)
    timeout_seconds: int = Field(default=120, ge=10, le=3600)
    depth: int = Field(default=0, ge=0)
    model: str | None = None
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)


class FanOutRequestBody(BaseModel):
    """Body for the fan-out delegation endpoint."""

    requests: list[DelegateRequestBody] = Field(..., min_length=1, max_length=20)


class CapabilityMatchRequest(BaseModel):
    """Body for the capability match endpoint."""

    capability_id: str
    exclude_agents: list[str] = Field(default_factory=list)


class BudgetSplitRequest(BaseModel):
    """Body for the budget split endpoint."""

    parent_budget: int = Field(ge=100, le=200000)
    num_children: int = Field(ge=1, le=20)
    reserve_fraction: float = Field(default=0.2, ge=0.0, lt=1.0)


class DelegationResultResponse(BaseModel):
    """Serialisable delegation result for the API layer."""

    delegation_id: str
    target_agent: str
    status: str
    output: dict[str, Any] = Field(default_factory=dict)
    raw_response: str = ""
    tokens_used: int = 0
    model: str = ""
    duration_seconds: float = 0.0
    error: str = ""
    depth: int = 0


# -- routes ---------------------------------------------------------------


@router.post(
    "/delegate",
    response_model=DelegationResultResponse,
    dependencies=[require_scope("agents:invoke")],
)
async def delegate_task(
    body: DelegateRequestBody,
    request: Request,
) -> DelegationResultResponse:
    """Delegate a single task to a named agent or by capability match."""
    manager = _get_delegation_manager(request)

    delegation_request = DelegationRequest(
        parent_agent=body.parent_agent,
        target_agent=body.target_agent,
        required_capability=body.required_capability,
        inputs=body.inputs,
        token_budget=body.token_budget,
        timeout_seconds=body.timeout_seconds,
        depth=body.depth,
        model=body.model,
        temperature=body.temperature,
    )

    result = await manager.delegate(delegation_request)
    return _to_response(result)


@router.post(
    "/fan-out",
    dependencies=[require_scope("agents:invoke")],
)
async def delegate_fan_out(
    body: FanOutRequestBody,
    request: Request,
) -> dict[str, Any]:
    """Delegate multiple tasks in parallel and aggregate results."""
    manager = _get_delegation_manager(request)

    delegation_requests = [
        DelegationRequest(
            parent_agent=req.parent_agent,
            target_agent=req.target_agent,
            required_capability=req.required_capability,
            inputs=req.inputs,
            token_budget=req.token_budget,
            timeout_seconds=req.timeout_seconds,
            depth=req.depth,
            model=req.model,
            temperature=req.temperature,
        )
        for req in body.requests
    ]

    results = await manager.delegate_fan_out(delegation_requests)
    aggregated: dict[str, Any] = DelegationManager.aggregate_results(results)
    return aggregated


@router.post(
    "/match-capability",
    response_model=list[CapabilityMatch],
    dependencies=[require_scope("agents:read")],
)
async def match_capability(
    body: CapabilityMatchRequest,
    request: Request,
) -> list[CapabilityMatch]:
    """Find agents that match a given spec capability."""
    manager = _get_delegation_manager(request)
    matches = manager.match_capability(
        body.capability_id,
        exclude_agents=body.exclude_agents,
    )
    return matches


@router.post(
    "/split-budget",
    dependencies=[require_scope("agents:read")],
)
async def split_budget(
    body: BudgetSplitRequest,
) -> dict[str, Any]:
    """Calculate how to split a token budget across N children."""
    try:
        budgets = DelegationManager.split_budget(
            body.parent_budget,
            body.num_children,
            reserve_fraction=body.reserve_fraction,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    reserved = int(body.parent_budget * body.reserve_fraction)
    return {
        "parent_budget": body.parent_budget,
        "reserved_for_parent": reserved,
        "per_child_budget": budgets[0] if budgets else 0,
        "num_children": body.num_children,
        "child_budgets": budgets,
    }


@router.get(
    "/history",
    dependencies=[require_scope("agents:read")],
)
async def delegation_history(
    request: Request,
    limit: int = 50,
) -> list[DelegationResultResponse]:
    """Return recent delegation history (most recent last)."""
    manager = _get_delegation_manager(request)
    history = manager.history
    recent = history[-limit:] if len(history) > limit else history
    return [_to_response(r) for r in recent]


# -- helpers ---------------------------------------------------------------


def _to_response(result: DelegationResult) -> DelegationResultResponse:
    return DelegationResultResponse(
        delegation_id=result.delegation_id,
        target_agent=result.target_agent,
        status=result.status.value,
        output=result.output,
        raw_response=result.raw_response,
        tokens_used=result.tokens_used,
        model=result.model,
        duration_seconds=result.duration_seconds,
        error=result.error,
        depth=result.depth,
    )
