"""API routes for knowledge source management and manual ingestion (P70)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from agent33.knowledge.models import IngestionResult, KnowledgeSource, SourceType
from agent33.knowledge.service import KnowledgeIngestionService
from agent33.security.permissions import require_scope

router = APIRouter(prefix="/v1/knowledge", tags=["knowledge"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class AddSourceRequest(BaseModel):
    """Request body for adding a knowledge source."""

    name: str
    source_type: SourceType
    url: str | None = None
    local_path: str | None = None
    cron_expression: str = "0 */6 * * *"
    enabled: bool = True


class SourceListResponse(BaseModel):
    """Response listing all knowledge sources."""

    sources: list[KnowledgeSource] = Field(default_factory=list)
    count: int = 0


class SourceStatusResponse(BaseModel):
    """Response showing last ingestion status for a source."""

    source: KnowledgeSource
    last_result: IngestionResult | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_knowledge_service(request: Request) -> KnowledgeIngestionService:
    """Retrieve KnowledgeIngestionService from app state."""
    svc = getattr(request.app.state, "knowledge_service", None)
    if not isinstance(svc, KnowledgeIngestionService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Knowledge ingestion service not initialized",
        )
    return svc


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/sources",
    response_model=KnowledgeSource,
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_scope("agents:write")],
)
async def add_source(request: Request, body: AddSourceRequest) -> KnowledgeSource:
    """Register a new knowledge source for scheduled ingestion."""
    svc = _get_knowledge_service(request)
    source = svc.add_source(
        name=body.name,
        source_type=body.source_type,
        url=body.url,
        local_path=body.local_path,
        cron_expression=body.cron_expression,
        enabled=body.enabled,
    )
    return source


@router.get(
    "/sources",
    response_model=SourceListResponse,
    dependencies=[require_scope("agents:read")],
)
async def list_sources(request: Request) -> SourceListResponse:
    """List all registered knowledge sources."""
    svc = _get_knowledge_service(request)
    sources = svc.list_sources()
    return SourceListResponse(sources=sources, count=len(sources))


@router.delete(
    "/sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[require_scope("agents:write")],
)
async def delete_source(request: Request, source_id: str) -> None:
    """Remove a knowledge source."""
    svc = _get_knowledge_service(request)
    removed = svc.remove_source(source_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source {source_id!r} not found",
        )


@router.post(
    "/sources/{source_id}/ingest",
    response_model=IngestionResult,
    dependencies=[require_scope("agents:write")],
)
async def trigger_ingest(request: Request, source_id: str) -> IngestionResult:
    """Manually trigger ingestion for a specific source."""
    svc = _get_knowledge_service(request)
    source = svc.get_source(source_id)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source {source_id!r} not found",
        )
    result = await svc.ingest_source(source_id)
    return result


@router.get(
    "/sources/{source_id}/status",
    response_model=SourceStatusResponse,
    dependencies=[require_scope("agents:read")],
)
async def source_status(request: Request, source_id: str) -> SourceStatusResponse:
    """Show the last ingestion status for a source."""
    svc = _get_knowledge_service(request)
    source = svc.get_source(source_id)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source {source_id!r} not found",
        )
    last_result = svc.get_last_result(source_id)
    return SourceStatusResponse(source=source, last_result=last_result)
