"""Memory search and observation API routes."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator, model_validator

from agent33.security.permissions import require_scope

router = APIRouter(prefix="/v1/memory", tags=["memory"])


class MemorySearchRequest(BaseModel):
    query: str
    level: str = "index"  # index | timeline | full
    top_k: int = 10


class MemorySearchResponse(BaseModel):
    results: list[dict[str, Any]]


class SummarizeResponse(BaseModel):
    summary: str
    key_facts: list[str]
    tags: list[str]


def _get_user_subject(request: Request) -> str:
    """Extract the authenticated user's subject from the request state."""
    payload = getattr(request.state, "user", None)
    if payload is None:
        return ""
    result: str = payload.sub
    return result


@router.post(
    "/search",
    response_model=MemorySearchResponse,
    dependencies=[require_scope("agents:read")],
)
async def search_memory(req: MemorySearchRequest, request: Request) -> MemorySearchResponse:
    """Search memory with progressive recall at specified detail level."""
    recall = getattr(request.app.state, "progressive_recall", None)
    if recall is None:
        raise HTTPException(503, "Memory system not initialized")

    results = await recall.search(req.query, level=req.level, top_k=req.top_k)
    return MemorySearchResponse(
        results=[
            {
                "level": r.level,
                "content": r.content,
                "citations": r.citations,
                "token_estimate": r.token_estimate,
            }
            for r in results
        ]
    )


@router.get("/sessions/{session_id}/observations", dependencies=[require_scope("agents:read")])
async def list_observations(session_id: str, request: Request) -> dict[str, Any]:
    """List observations for a session.

    Only returns observations belonging to the authenticated user's sessions.
    """
    capture = getattr(request.app.state, "observation_capture", None)
    if capture is None:
        raise HTTPException(503, "Observation capture not initialized")

    user_subject = _get_user_subject(request)

    # Return buffered observations matching session_id AND owned by the requesting user.
    # Observations include agent_name which can be traced to the invoking user.
    observations = [
        {
            "id": o.id,
            "session_id": o.session_id,
            "agent_name": o.agent_name,
            "event_type": o.event_type,
            "content": o.content[:500],
            "tags": o.tags,
            "timestamp": o.timestamp.isoformat(),
        }
        for o in capture._buffer
        if o.session_id == session_id
        and (not user_subject or getattr(o, "user_subject", None) == user_subject)
    ]
    return {"session_id": session_id, "observations": observations}


@router.post(
    "/sessions/{session_id}/summarize",
    response_model=SummarizeResponse,
    dependencies=[require_scope("agents:write")],
)
async def summarize_session(session_id: str, request: Request) -> SummarizeResponse:
    """Trigger summarization for a session's observations.

    Only allows summarization of sessions owned by the authenticated user.
    """
    capture = getattr(request.app.state, "observation_capture", None)
    summarizer = getattr(request.app.state, "session_summarizer", None)
    if capture is None or summarizer is None:
        raise HTTPException(503, "Memory system not initialized")

    user_subject = _get_user_subject(request)

    observations = [
        o
        for o in capture._buffer
        if o.session_id == session_id
        and (not user_subject or getattr(o, "user_subject", None) == user_subject)
    ]
    if not observations:
        raise HTTPException(404, f"No observations for session {session_id}")

    result = await summarizer.auto_summarize(session_id, observations)
    return SummarizeResponse(
        summary=result.get("summary", ""),
        key_facts=result.get("key_facts", []),
        tags=result.get("tags", []),
    )


# ── Ingestion pipeline ──────────────────────────────────────────────────


class IngestRequest(BaseModel):
    content: str
    content_type: Literal["text/plain", "text/markdown"] = "text/plain"
    metadata: dict[str, Any] = Field(default_factory=dict)
    chunk_strategy: Literal["token_aware", "character"] = "token_aware"
    chunk_size: int = 1200  # tokens for token_aware, chars for character
    chunk_overlap: int = 100

    @field_validator("chunk_size")
    @classmethod
    def chunk_size_must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("chunk_size must be greater than 0")
        return v

    @field_validator("chunk_overlap")
    @classmethod
    def chunk_overlap_must_be_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("chunk_overlap must be non-negative")
        return v

    @model_validator(mode="after")
    def validate_overlap_less_than_size(self) -> IngestRequest:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError(
                f"chunk_overlap ({self.chunk_overlap}) must be less than "
                f"chunk_size ({self.chunk_size})"
            )
        return self


class IngestResponse(BaseModel):
    chunks_created: int
    record_ids: list[int]
    bm25_indexed: bool


@router.post(
    "/ingest",
    response_model=IngestResponse,
    status_code=201,
    dependencies=[require_scope("agents:write")],
)
async def ingest_document(req: IngestRequest, request: Request) -> IngestResponse:
    """Ingest a document: chunk -> embed -> store in pgvector -> add to BM25."""
    from agent33.memory.ingestion import DocumentIngester, TokenAwareChunker

    long_term_memory = getattr(request.app.state, "long_term_memory", None)
    if long_term_memory is None:
        raise HTTPException(503, "Memory system not initialized")

    # Get the active embedder (cache-wrapped or raw provider)
    embedder = getattr(request.app.state, "embedding_cache", None) or getattr(
        request.app.state, "embedding_provider", None
    )
    if embedder is None:
        raise HTTPException(503, "Embedding provider not initialized")

    bm25_index = getattr(request.app.state, "bm25_index", None)

    # Chunk the content
    if req.chunk_strategy == "token_aware":
        chunker = TokenAwareChunker(
            chunk_tokens=req.chunk_size,
            overlap_tokens=req.chunk_overlap,
        )
        if req.content_type == "text/markdown":
            chunks = chunker.chunk_markdown(req.content)
        else:
            chunks = chunker.chunk_text(req.content)
    else:
        ingester = DocumentIngester()
        if req.content_type == "text/markdown":
            chunks = ingester.ingest_markdown(
                req.content,
                chunk_size=req.chunk_size,
                overlap=req.chunk_overlap,
            )
        else:
            chunks = ingester.ingest_text(
                req.content,
                chunk_size=req.chunk_size,
                overlap=req.chunk_overlap,
            )

    if not chunks:
        return IngestResponse(chunks_created=0, record_ids=[], bm25_indexed=False)

    # Embed all chunks
    texts = [c.text for c in chunks]
    embeddings = await embedder.embed_batch(texts)

    # Store in pgvector
    record_ids: list[int] = []
    for chunk, embedding in zip(chunks, embeddings, strict=True):
        meta = {**req.metadata, **chunk.metadata}
        rid = await long_term_memory.store(chunk.text, embedding, meta)
        record_ids.append(rid)

    # Add to BM25 index (batch for performance)
    bm25_indexed = False
    if bm25_index is not None:
        docs_for_bm25 = [(chunk.text, {**req.metadata, **chunk.metadata}) for chunk in chunks]
        bm25_index.add_documents(docs_for_bm25)
        bm25_indexed = True

    return IngestResponse(
        chunks_created=len(chunks),
        record_ids=record_ids,
        bm25_indexed=bm25_indexed,
    )
