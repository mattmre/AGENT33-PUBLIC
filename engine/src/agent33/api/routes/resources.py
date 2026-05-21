"""Resource manifest service APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from agent33.resources.manifest import ResourceKind, ResourceManifest  # noqa: TC001
from agent33.resources.service import (
    ResourceSearchResult,
    ResourceSubmission,
    get_resource_service,
)
from agent33.security.permissions import require_scope

router = APIRouter(prefix="/v1/resources", tags=["resources"])


@router.get("/search", dependencies=[require_scope("workflows:read")])
async def search_resources(
    query: str = "",
    kind: ResourceKind | None = None,
    limit: int = 50,
) -> ResourceSearchResult:
    return get_resource_service().search(query=query, kind=kind, limit=limit)


@router.get("/{resource_id}", dependencies=[require_scope("workflows:read")])
async def get_resource(resource_id: str) -> ResourceManifest:
    manifest = get_resource_service().get(resource_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"Resource not found: {resource_id}")
    return manifest


@router.post("/validate", dependencies=[require_scope("workflows:read")])
async def validate_resource(payload: dict[str, Any]) -> ResourceManifest:
    return get_resource_service().validate(payload)


@router.post("/submit", dependencies=[require_scope("tools:execute")])
async def submit_resource(payload: dict[str, Any]) -> ResourceSubmission:
    return get_resource_service().submit(payload)


@router.post("/{resource_id}/quarantine", dependencies=[require_scope("tools:execute")])
async def quarantine_resource(resource_id: str, payload: dict[str, Any]) -> ResourceSubmission:
    submission = get_resource_service().quarantine(resource_id, note=str(payload.get("note", "")))
    if submission is None:
        raise HTTPException(status_code=404, detail=f"Resource not found: {resource_id}")
    return submission


@router.post("/{resource_id}/feedback", dependencies=[require_scope("tools:execute")])
async def record_resource_feedback(
    resource_id: str,
    payload: dict[str, Any],
) -> ResourceSubmission:
    submission = get_resource_service().feedback(resource_id, note=str(payload.get("note", "")))
    if submission is None:
        raise HTTPException(
            status_code=404,
            detail=f"Resource submission not found: {resource_id}",
        )
    return submission
