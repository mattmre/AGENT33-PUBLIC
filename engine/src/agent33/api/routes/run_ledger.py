"""API surface for the task/run/evidence ledger foundation."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from agent33.ops.run_ledger import RunLedgerRepository
from agent33.security.permissions import require_scope

router = APIRouter(prefix="/v1/run-ledger", tags=["run-ledger"])
_repository = RunLedgerRepository()


def get_run_ledger_repository() -> RunLedgerRepository:
    return _repository


def _tenant_id(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if user is None:
        return "default"
    return getattr(user, "tenant_id", "default") or "default"


@router.get("", dependencies=[require_scope("workflows:read")])
async def list_run_ledger(request: Request) -> dict[str, Any]:
    """Return tenant-scoped task/run/evidence records."""
    records = get_run_ledger_repository().list_records(_tenant_id(request))
    return {
        "records": [
            {
                "task": record.task,
                "run": record.run,
                "events": record.events,
                "evidence": record.evidence,
            }
            for record in records
        ]
    }


@router.post("/{run_id}/checkpoints", dependencies=[require_scope("workflows:write")])
async def create_run_replay_checkpoint(
    run_id: str,
    request: Request,
    body: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Create a replay checkpoint anchored to the run ledger timeline."""
    payload = body or {}
    try:
        checkpoint = get_run_ledger_repository().create_replay_checkpoint(
            _tenant_id(request),
            run_id,
            event_id=payload.get("event_id", ""),
            label=payload.get("label", ""),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"checkpoint": checkpoint}


@router.get("/{run_id}/resume-plan", dependencies=[require_scope("workflows:read")])
async def get_run_resume_plan(run_id: str, request: Request) -> dict[str, Any]:
    """Return the latest replay checkpoint and timeline items still pending after it."""
    try:
        plan = get_run_ledger_repository().build_resume_plan(_tenant_id(request), run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "checkpoint": plan.checkpoint,
        "run": plan.run,
        "resume_status": plan.resume_status,
        "resume_from_event_id": plan.resume_from_event_id,
        "pending_timeline": plan.pending_timeline,
        "blockers": plan.blockers,
    }
