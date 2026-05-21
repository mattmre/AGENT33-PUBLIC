"""FastAPI router for autonomy budget enforcement and policy automation."""

# NOTE: no ``from __future__ import annotations`` — Pydantic needs these
# types at runtime for request-body validation.

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent33.autonomy.models import BudgetState, EscalationUrgency
from agent33.autonomy.service import (
    AutonomyService,
    BudgetNotFoundError,
    EnforcerNotFoundError,
    InvalidStateTransitionError,
)
from agent33.security.permissions import require_scope

logger = structlog.get_logger()

router = APIRouter(prefix="/v1/autonomy", tags=["autonomy"])

# Singleton service
_service = AutonomyService()


def set_autonomy_service(service: AutonomyService) -> None:
    """Inject a shared autonomy service instance (called from lifespan)."""
    global _service  # noqa: PLW0603
    _service = service


def get_autonomy_service() -> AutonomyService:
    """Return the autonomy service singleton (for testing injection)."""
    return _service


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CreateBudgetRequest(BaseModel):
    task_id: str = ""
    agent_id: str = ""
    in_scope: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    default_escalation_target: str = "orchestrator"


class TransitionRequest(BaseModel):
    to_state: BudgetState
    approved_by: str = ""


class CheckFileRequest(BaseModel):
    path: str
    mode: str = "read"  # "read" or "write"
    lines: int = 0


class CheckCommandRequest(BaseModel):
    command: str


class CheckNetworkRequest(BaseModel):
    domain: str


class TriggerEscalationRequest(BaseModel):
    description: str
    target: str = ""
    urgency: EscalationUrgency = EscalationUrgency.NORMAL


# ---------------------------------------------------------------------------
# Budget CRUD routes
# ---------------------------------------------------------------------------


@router.post(
    "/budgets",
    status_code=201,
    dependencies=[require_scope("tools:execute")],
)
async def create_budget(body: CreateBudgetRequest) -> dict[str, Any]:
    """Create a new autonomy budget in DRAFT state."""
    budget = _service.create_budget(
        task_id=body.task_id,
        agent_id=body.agent_id,
        in_scope=body.in_scope,
        out_of_scope=body.out_of_scope,
        default_escalation_target=body.default_escalation_target,
    )
    return {
        "budget_id": budget.budget_id,
        "state": budget.state.value,
        "task_id": budget.task_id,
        "agent_id": budget.agent_id,
    }


@router.get(
    "/budgets",
    dependencies=[require_scope("workflows:read")],
)
async def list_budgets(
    state: str | None = None,
    task_id: str | None = None,
    agent_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List budgets with optional filters."""
    state_filter = BudgetState(state) if state else None
    budgets = _service.list_budgets(
        state=state_filter, task_id=task_id, agent_id=agent_id, limit=limit
    )
    return [
        {
            "budget_id": b.budget_id,
            "state": b.state.value,
            "task_id": b.task_id,
            "agent_id": b.agent_id,
            "created_at": b.created_at.isoformat(),
        }
        for b in budgets
    ]


@router.get(
    "/budgets/{budget_id}",
    dependencies=[require_scope("workflows:read")],
)
async def get_budget(budget_id: str) -> dict[str, Any]:
    """Get budget details."""
    try:
        budget = _service.get_budget(budget_id)
    except BudgetNotFoundError:
        raise HTTPException(status_code=404, detail=f"Budget not found: {budget_id}") from None
    return budget.model_dump(mode="json")


@router.delete(
    "/budgets/{budget_id}",
    dependencies=[require_scope("tools:execute")],
)
async def delete_budget(budget_id: str) -> dict[str, str]:
    """Delete a budget (only DRAFT or REJECTED state)."""
    try:
        _service.delete_budget(budget_id)
    except BudgetNotFoundError:
        raise HTTPException(status_code=404, detail=f"Budget not found: {budget_id}") from None
    except InvalidStateTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Lifecycle routes
# ---------------------------------------------------------------------------


@router.post(
    "/budgets/{budget_id}/transition",
    dependencies=[require_scope("tools:execute")],
)
async def transition_budget(budget_id: str, body: TransitionRequest) -> dict[str, Any]:
    """Transition a budget to a new state."""
    try:
        budget = _service.transition(budget_id, body.to_state, approved_by=body.approved_by)
    except BudgetNotFoundError:
        raise HTTPException(status_code=404, detail=f"Budget not found: {budget_id}") from None
    except InvalidStateTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"budget_id": budget.budget_id, "state": budget.state.value}


@router.post(
    "/budgets/{budget_id}/activate",
    dependencies=[require_scope("tools:execute")],
)
async def activate_budget(budget_id: str) -> dict[str, Any]:
    """Activate a budget (from DRAFT or PENDING_APPROVAL)."""
    try:
        budget = _service.activate(budget_id)
    except BudgetNotFoundError:
        raise HTTPException(status_code=404, detail=f"Budget not found: {budget_id}") from None
    except InvalidStateTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"budget_id": budget.budget_id, "state": budget.state.value}


@router.post(
    "/budgets/{budget_id}/suspend",
    dependencies=[require_scope("tools:execute")],
)
async def suspend_budget(budget_id: str) -> dict[str, Any]:
    """Suspend an active budget."""
    try:
        budget = _service.suspend(budget_id)
    except BudgetNotFoundError:
        raise HTTPException(status_code=404, detail=f"Budget not found: {budget_id}") from None
    except InvalidStateTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"budget_id": budget.budget_id, "state": budget.state.value}


@router.post(
    "/budgets/{budget_id}/complete",
    dependencies=[require_scope("tools:execute")],
)
async def complete_budget(budget_id: str) -> dict[str, Any]:
    """Mark a budget as completed."""
    try:
        budget = _service.complete(budget_id)
    except BudgetNotFoundError:
        raise HTTPException(status_code=404, detail=f"Budget not found: {budget_id}") from None
    except InvalidStateTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"budget_id": budget.budget_id, "state": budget.state.value}


# ---------------------------------------------------------------------------
# Preflight route
# ---------------------------------------------------------------------------


@router.get(
    "/budgets/{budget_id}/preflight",
    dependencies=[require_scope("workflows:read")],
)
async def run_preflight(budget_id: str) -> dict[str, Any]:
    """Run preflight checks on a budget."""
    try:
        report = _service.run_preflight(budget_id)
    except BudgetNotFoundError:
        raise HTTPException(status_code=404, detail=f"Budget not found: {budget_id}") from None
    return report.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Enforcement routes
# ---------------------------------------------------------------------------


@router.post(
    "/budgets/{budget_id}/enforcer",
    status_code=201,
    dependencies=[require_scope("tools:execute")],
)
async def create_enforcer(budget_id: str) -> dict[str, str]:
    """Create a runtime enforcer for an active budget."""
    try:
        _service.create_enforcer(budget_id)
    except BudgetNotFoundError:
        raise HTTPException(status_code=404, detail=f"Budget not found: {budget_id}") from None
    except InvalidStateTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"budget_id": budget_id, "status": "enforcer_created"}


@router.post(
    "/budgets/{budget_id}/enforce/file",
    dependencies=[require_scope("tools:execute")],
)
async def enforce_file(budget_id: str, body: CheckFileRequest) -> dict[str, Any]:
    """Check file access against budget enforcement rules."""
    try:
        result = _service.enforce_file(
            budget_id=budget_id,
            path=body.path,
            mode=body.mode,
            lines=body.lines,
        )
    except EnforcerNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"No enforcer for budget: {budget_id}",
        ) from None
    return {"result": result.value, "path": body.path, "mode": body.mode}


@router.post(
    "/budgets/{budget_id}/enforce/command",
    dependencies=[require_scope("tools:execute")],
)
async def enforce_command(budget_id: str, body: CheckCommandRequest) -> dict[str, Any]:
    """Check command execution against budget enforcement rules."""
    try:
        result = _service.enforce_command(budget_id=budget_id, command=body.command)
    except EnforcerNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"No enforcer for budget: {budget_id}",
        ) from None
    return {"result": result.value, "command": body.command}


@router.post(
    "/budgets/{budget_id}/enforce/network",
    dependencies=[require_scope("tools:execute")],
)
async def enforce_network(budget_id: str, body: CheckNetworkRequest) -> dict[str, Any]:
    """Check network access against budget enforcement rules."""
    try:
        result = _service.enforce_network(budget_id=budget_id, domain=body.domain)
    except EnforcerNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"No enforcer for budget: {budget_id}",
        ) from None
    return {"result": result.value, "domain": body.domain}


# ---------------------------------------------------------------------------
# Escalation routes
# ---------------------------------------------------------------------------


@router.get(
    "/escalations",
    dependencies=[require_scope("workflows:read")],
)
async def list_escalations(
    budget_id: str | None = None,
    unresolved_only: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List escalation records."""
    records = _service.list_escalations(
        budget_id=budget_id, unresolved_only=unresolved_only, limit=limit
    )
    return [r.model_dump(mode="json") for r in records]


@router.post(
    "/budgets/{budget_id}/escalate",
    status_code=201,
    dependencies=[require_scope("tools:execute")],
)
async def trigger_escalation(budget_id: str, body: TriggerEscalationRequest) -> dict[str, Any]:
    """Manually trigger an escalation for a budget."""
    try:
        record = _service.trigger_escalation(
            budget_id=budget_id,
            description=body.description,
            target=body.target,
            urgency=body.urgency,
        )
    except EnforcerNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"No enforcer for budget: {budget_id}",
        ) from None
    return {
        "escalation_id": record.escalation_id,
        "target": record.target,
        "urgency": record.urgency.value,
    }


@router.post(
    "/escalations/{escalation_id}/acknowledge",
    dependencies=[require_scope("tools:execute")],
)
async def acknowledge_escalation(escalation_id: str) -> dict[str, Any]:
    """Acknowledge an escalation."""
    found = _service.acknowledge_escalation(escalation_id)
    if not found:
        raise HTTPException(
            status_code=404,
            detail=f"Escalation not found: {escalation_id}",
        )
    return {"escalation_id": escalation_id, "acknowledged": True}


@router.post(
    "/escalations/{escalation_id}/resolve",
    dependencies=[require_scope("tools:execute")],
)
async def resolve_escalation(escalation_id: str) -> dict[str, Any]:
    """Resolve an escalation."""
    found = _service.resolve_escalation(escalation_id)
    if not found:
        raise HTTPException(
            status_code=404,
            detail=f"Escalation not found: {escalation_id}",
        )
    return {"escalation_id": escalation_id, "resolved": True}
