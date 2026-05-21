"""Checkpoint listing route — GET /v1/workflows/{run_id}/checkpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from agent33.security.permissions import require_scope

router = APIRouter(prefix="/v1/workflows", tags=["checkpoints"])


@router.get("/{run_id}/checkpoints", dependencies=[require_scope("operator:read")])
async def list_checkpoints(run_id: str, req: Request) -> dict[str, Any]:
    """Return checkpoint records saved for *run_id*.

    When checkpoint persistence is disabled (no CheckpointManager on app.state)
    or no checkpoints have been saved, returns an empty list.
    """
    checkpoint_manager = getattr(req.app.state, "checkpoint_manager", None)
    if checkpoint_manager is None:
        return {"run_id": run_id, "checkpoints": []}

    records = await checkpoint_manager.list_checkpoints(workflow_id=run_id)
    return {"run_id": run_id, "checkpoints": records}
