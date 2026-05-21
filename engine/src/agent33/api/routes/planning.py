"""FastAPI router for planning and replanning operations."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from agent33.planning.plans import (
    PlanAction,
    PlannerService,
    PlanSummary,
    ReplanDecision,
    ReplanEvent,
)
from agent33.security.permissions import require_scope

router = APIRouter(prefix="/v1/planning", tags=["planning"])

_planner = PlannerService()


def set_planner_service(service: PlannerService) -> None:
    """Inject a shared PlannerService instance (called from lifespan)."""
    global _planner  # noqa: PLW0603
    _planner = service


def get_planner_service() -> PlannerService:
    """Return the active PlannerService singleton."""
    return _planner


@router.post("/plans", dependencies=[require_scope("workflows:write")], status_code=201)
async def create_plan(
    plan_id: str,
    objective: str,
    actions: list[PlanAction],
    blockers: list[str] | None = None,
) -> PlanSummary:
    """Create a new plan and return its summary."""
    if _planner.get_plan(plan_id) is not None:
        raise HTTPException(status_code=409, detail=f"Plan '{plan_id}' already exists")
    return _planner.create_plan(
        plan_id=plan_id,
        objective=objective,
        actions=actions,
        blockers=blockers,
    )


@router.get("/plans/{plan_id}", dependencies=[require_scope("workflows:read")])
async def get_plan(plan_id: str) -> PlanSummary:
    """Retrieve a plan summary by ID."""
    plan = _planner.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Plan '{plan_id}' not found")
    return _planner.summarize(plan)


@router.get("/plans", dependencies=[require_scope("workflows:read")])
async def list_plans() -> list[PlanSummary]:
    """List all plans."""
    return [_planner.summarize(plan) for plan in _planner.list_plans()]


@router.delete("/plans/{plan_id}", dependencies=[require_scope("workflows:write")])
async def delete_plan(plan_id: str) -> dict[str, str]:
    """Delete a plan."""
    if not _planner.delete_plan(plan_id):
        raise HTTPException(status_code=404, detail=f"Plan '{plan_id}' not found")
    return {"message": f"Plan '{plan_id}' deleted"}


@router.post("/replan", dependencies=[require_scope("workflows:write")])
async def evaluate_replan(events: list[ReplanEvent]) -> ReplanDecision:
    """Evaluate whether replanning is needed based on a list of events."""
    return _planner.evaluate_replan(events)
