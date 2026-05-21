"""Unified Doctor Center routes."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from agent33.api.routes.operator import get_operator_service
from agent33.api.routes.run_ledger import get_run_ledger_repository
from agent33.config import settings
from agent33.ops.doctor_status import build_doctor_status
from agent33.ops.first_success import DEFAULT_FIRST_SUCCESS_PLAN, create_first_success_smoke_run
from agent33.security.permissions import require_scope
from agent33.state_paths import RuntimeStatePaths

router = APIRouter(prefix="/v1/doctor", tags=["doctor"])
OperatorServiceDep = Annotated[Any, Depends(get_operator_service)]


def _tenant_id(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if user is None:
        return "default"
    return getattr(user, "tenant_id", "default") or "default"


@router.get("/status", dependencies=[require_scope("operator:read")])
async def doctor_status(svc: OperatorServiceDep) -> dict[str, Any]:
    """Return unified setup/model/tool/resource diagnostic status."""
    status = build_doctor_status(await svc.run_doctor())
    return asdict(status)


@router.get("/state-paths", dependencies=[require_scope("operator:read")])
async def state_path_audit(request: Request) -> dict[str, Any]:
    """Return restart-safety status for configured durable state paths."""
    state_paths = getattr(request.app.state, "runtime_state_paths", None)
    if state_paths is None:
        state_paths = RuntimeStatePaths.from_app_root(Path.cwd())
    audit = state_paths.audit_configured_state_paths(settings)
    return asdict(audit)


@router.get("/first-success", dependencies=[require_scope("operator:read")])
async def first_success_plan() -> dict[str, Any]:
    """Return the guided first-success smoke task plan."""
    return asdict(DEFAULT_FIRST_SUCCESS_PLAN)


@router.post("/first-success/run", dependencies=[require_scope("workflows:write")])
async def start_first_success_run(request: Request) -> dict[str, Any]:
    """Record a safe first-success smoke task as a normal run-ledger record."""
    record = create_first_success_smoke_run(get_run_ledger_repository(), _tenant_id(request))
    return {
        "task": record.task,
        "run": record.run,
        "events": record.events,
        "evidence": record.evidence,
    }
