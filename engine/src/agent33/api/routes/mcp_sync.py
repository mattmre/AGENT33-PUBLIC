"""FastAPI router for cross-CLI MCP configuration sync operations."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent33.mcp_server.sync import (
    CLITarget,
    NormalizedMCPEntry,
    SyncConfig,
    diff_sync,
    get_target_paths,
    pull_sync,
    push_sync,
)
from agent33.security.permissions import require_scope

router = APIRouter(prefix="/v1/mcp/sync", tags=["mcp-sync"])

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class PushRequest(BaseModel):
    """Request body for push sync operation."""

    targets: list[str] = Field(default_factory=lambda: ["claude_code"])
    entry: NormalizedMCPEntry = Field(default_factory=NormalizedMCPEntry)
    force: bool = False


class PullRequest(BaseModel):
    """Request body for pull sync operation."""

    target: str = "claude_code"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/push", dependencies=[require_scope("admin")])
async def push_mcp_config(body: PushRequest) -> dict[str, Any]:
    """Push AGENT-33 MCP registration to CLI configs."""
    try:
        targets = [CLITarget(t) for t in body.targets]
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid target: {exc}",
        ) from exc
    config = SyncConfig(entry=body.entry, targets=targets, force=body.force)
    results = push_sync(config, backup=True)
    return {"results": [r.model_dump(mode="json") for r in results]}


@router.post("/pull", dependencies=[require_scope("admin")])
async def pull_mcp_config(body: PullRequest) -> dict[str, Any]:
    """Pull MCP server registrations from a CLI config."""
    try:
        target = CLITarget(body.target)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid target: {exc}",
        ) from exc
    result = pull_sync(target)
    return result.model_dump(mode="json")


@router.get("/diff", dependencies=[require_scope("agents:read")])
async def diff_mcp_config() -> dict[str, Any]:
    """Diff AGENT-33 registration across all CLI targets."""
    entries = diff_sync()
    return {"entries": [e.model_dump(mode="json") for e in entries]}


@router.get("/targets", dependencies=[require_scope("agents:read")])
async def list_sync_targets() -> dict[str, Any]:
    """List supported CLI targets and their config file paths."""
    return {"targets": get_target_paths()}
