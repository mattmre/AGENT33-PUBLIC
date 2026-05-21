"""Embedding model hot-swap admin API endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from agent33.memory.embedding_swap import (
    EmbeddingModelInfo,
    EmbeddingSwapManager,
    SwapRecord,
    SwapStatus,
)
from agent33.security.permissions import require_scope

router = APIRouter(prefix="/v1/embeddings", tags=["embeddings"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_swap_manager(request: Request) -> EmbeddingSwapManager:
    """Resolve the EmbeddingSwapManager from app state."""
    manager: EmbeddingSwapManager | None = getattr(request.app.state, "embedding_swap", None)
    if manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Embedding swap manager not initialized",
        )
    return manager


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class RegisterModelRequest(BaseModel):
    """Body for registering a new embedding model."""

    model_id: str = Field(description="Unique model identifier")
    provider: str = Field(description="Provider name")
    dimensions: int = Field(description="Vector dimensionality", gt=0)
    max_tokens: int = Field(default=8192, description="Maximum input tokens")
    version: str = Field(default="1.0", description="Model version")
    description: str = Field(default="", description="Model description")


class SwapRequest(BaseModel):
    """Body for executing an embedding model swap."""

    target_model_id: str = Field(description="ID of the model to swap to")
    initiated_by: str = Field(default="admin", description="Who initiated the swap")


class SwapValidationResponse(BaseModel):
    """Result of swap validation."""

    valid: bool
    message: str


class ModelListResponse(BaseModel):
    """List of available embedding models."""

    models: list[EmbeddingModelInfo]
    count: int


class HistoryResponse(BaseModel):
    """Swap history response."""

    records: list[SwapRecord]
    count: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/current",
    response_model=EmbeddingModelInfo,
    dependencies=[require_scope("admin")],
)
async def get_current_model(request: Request) -> EmbeddingModelInfo:
    """Return the currently active embedding model info."""
    manager = _get_swap_manager(request)
    return manager.get_current_model()


@router.get(
    "/models",
    response_model=ModelListResponse,
    dependencies=[require_scope("admin")],
)
async def list_models(request: Request) -> ModelListResponse:
    """List all registered embedding models."""
    manager = _get_swap_manager(request)
    models = manager.list_available_models()
    return ModelListResponse(models=models, count=len(models))


@router.post(
    "/models",
    response_model=EmbeddingModelInfo,
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_scope("admin")],
)
async def register_model(
    body: RegisterModelRequest,
    request: Request,
) -> EmbeddingModelInfo:
    """Register a new embedding model as available for swapping."""
    manager = _get_swap_manager(request)
    model_info = EmbeddingModelInfo(
        model_id=body.model_id,
        provider=body.provider,
        dimensions=body.dimensions,
        max_tokens=body.max_tokens,
        version=body.version,
        description=body.description,
    )
    await manager.register_model(model_info)
    return model_info


@router.post(
    "/swap",
    response_model=SwapRecord,
    dependencies=[require_scope("admin")],
)
async def execute_swap(
    body: SwapRequest,
    request: Request,
) -> SwapRecord:
    """Execute an embedding model swap."""
    manager = _get_swap_manager(request)

    # Validate first
    valid, message = await manager.validate_swap(body.target_model_id)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )

    try:
        record = await manager.execute_swap(
            target_model_id=body.target_model_id,
            initiated_by=body.initiated_by,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if record.status == SwapStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=record.error or "Swap failed",
        )

    return record


@router.post(
    "/rollback",
    response_model=SwapRecord | None,
    dependencies=[require_scope("admin")],
)
async def rollback_swap(request: Request) -> SwapRecord | None:
    """Rollback the last completed swap."""
    manager = _get_swap_manager(request)
    record = await manager.rollback_last_swap()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No completed swap to rollback",
        )
    return record


@router.get(
    "/history",
    response_model=HistoryResponse,
    dependencies=[require_scope("admin")],
)
async def get_history(
    request: Request,
    limit: int = Query(default=50, gt=0, le=100),
) -> HistoryResponse:
    """Return swap history, most recent first."""
    manager = _get_swap_manager(request)
    records = manager.get_swap_history(limit=limit)
    return HistoryResponse(records=records, count=len(records))


@router.get(
    "/stats",
    dependencies=[require_scope("admin")],
)
async def get_stats(request: Request) -> dict[str, Any]:
    """Return embedding swap usage statistics."""
    manager = _get_swap_manager(request)
    return manager.get_current_stats()
