"""Workflow artifacts download route — GET /v1/workflows/{run_id}/artifacts."""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from agent33.security.permissions import require_scope

router = APIRouter(prefix="/v1/workflows", tags=["artifacts"])


@router.get("/{run_id}/artifacts", dependencies=[require_scope("operator:read")])
async def download_run_artifacts(run_id: str, request: Request) -> StreamingResponse:
    """Return step outputs for a workflow run as a downloadable zip archive.

    Each step in the run is serialised as ``{step_id}.json`` inside the zip.

    Returns 404 when the replay service is unavailable or when no steps have
    been recorded for the requested run — callers must not rely on an empty zip
    as a sentinel for "run not found".
    """
    replay = getattr(request.app.state, "execution_replay", None)

    if replay is None:
        raise HTTPException(
            status_code=404,
            detail="Replay service is not available; no artifacts can be retrieved.",
        )

    steps: list[Any] = replay.get_steps(run_id)
    if not steps:
        raise HTTPException(
            status_code=404,
            detail=f"No replay data found for run '{run_id}'.",
        )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for step in steps:
            payload: dict[str, Any] = {
                "step_id": step.step_id,
                "action_type": step.action_type,
                "status": step.status,
                "elapsed_ms": step.elapsed_ms,
                "error": step.error,
                "state_snapshot": step.state_snapshot,
            }
            zf.writestr(f"{step.step_id}.json", json.dumps(payload, indent=2))

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="run_{run_id}_artifacts.zip"'},
    )
