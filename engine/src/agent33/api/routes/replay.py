"""Workflow execution replay API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from agent33.security.permissions import require_scope

router = APIRouter(prefix="/v1/workflows", tags=["workflows"])


@router.get("/{run_id}/replay", dependencies=[require_scope("operator:read")])
async def get_workflow_replay(run_id: str, request: Request) -> dict[str, Any]:
    """Return the recorded replay steps for a completed workflow run."""
    replay = getattr(request.app.state, "execution_replay", None)
    if replay is None:
        return {"run_id": run_id, "steps": []}
    steps = replay.get_steps(run_id)
    return {
        "run_id": run_id,
        "steps": [
            {
                "step_id": s.step_id,
                "action_type": s.action_type,
                "status": s.status,
                "elapsed_ms": s.elapsed_ms,
                "error": s.error,
                "state_snapshot": s.state_snapshot,
            }
            for s in steps
        ],
    }
