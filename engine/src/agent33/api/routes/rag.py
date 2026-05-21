"""RAG query endpoint — POST /v1/rag/query."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from agent33.security.permissions import require_scope

router = APIRouter(prefix="/v1/rag", tags=["rag"])

logger = logging.getLogger(__name__)


class RagQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(5, ge=1, le=50)


class RagSourceResponse(BaseModel):
    text: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)
    retrieval_method: str = "vector"


class RagQueryResponse(BaseModel):
    augmented_prompt: str
    sources: list[RagSourceResponse]
    citations: list[str] = Field(default_factory=list)


@router.post("/query", dependencies=[require_scope("operator:read")])
async def rag_query(body: RagQueryRequest, req: Request) -> RagQueryResponse:
    """Run a RAG query against the engine's retrieval pipeline.

    Returns the augmented prompt, source documents, and citations.

    HTTP 503 is returned when the RAG pipeline is not initialised (lite mode
    or no DB).  HTTP 500 is returned for unexpected pipeline errors; the error
    is logged and the detail is surfaced so callers can distinguish transient
    failures from a permanently unavailable backend.
    """
    pipeline = getattr(req.app.state, "rag_pipeline", None)
    if pipeline is None:
        raise HTTPException(
            status_code=503,
            detail={"error": "rag_unavailable", "detail": "RAG pipeline not initialized"},
        )

    try:
        result = await pipeline.query(body.query)
    except (OSError, TimeoutError, ConnectionError) as exc:
        logger.warning("RAG pipeline transient error: %s", exc)
        raise HTTPException(
            status_code=503,
            detail={"error": "rag_unavailable", "detail": str(exc)},
        ) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("RAG pipeline unexpected error")
        raise HTTPException(
            status_code=500,
            detail={"error": "rag_error", "detail": str(exc)},
        ) from exc

    sources = [
        RagSourceResponse(
            text=src.text,
            score=src.score,
            metadata=src.metadata,
            retrieval_method=src.retrieval_method,
        )
        for src in result.sources
    ]
    citations: list[str] = list(getattr(result, "citations", None) or [])
    return RagQueryResponse(
        augmented_prompt=result.augmented_prompt,
        sources=sources,
        citations=citations,
    )
