"""FastAPI router for explanation generation and management."""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request

from agent33.explanation.fact_check import run_fact_check_hooks
from agent33.explanation.models import (
    DiffReviewRequest,
    ExplanationClaim,
    ExplanationMetadata,
    ExplanationMode,
    ExplanationRequest,
    PlanReviewRequest,
    ProjectRecapRequest,
)
from agent33.explanation.renderer import (
    render_diff_review,
    render_plan_review,
    render_project_recap,
)
from agent33.explanation.store import ExplanationStore
from agent33.security.permissions import require_scope

logger = structlog.get_logger()

router = APIRouter(prefix="/v1/explanations", tags=["explanations"])

# Module-level fallback store used when no app.state store is configured.
# Routes prefer app.state.explanation_store when available so that the store
# path can be configured at startup (and swapped to :memory: in tests).
_default_store: ExplanationStore | None = None


def _get_store(request: Request | None = None) -> ExplanationStore:
    """Return the active ExplanationStore.

    Precedence:
    1. ``request.app.state.explanation_store`` (set during lifespan or test fixture)
    2. The module-level ``_default_store`` singleton (lazy-initialised on first call)
    """
    global _default_store  # noqa: PLW0603

    if request is not None:
        store: ExplanationStore | None = getattr(request.app.state, "explanation_store", None)
        if store is not None:
            return store

    if _default_store is None:
        _default_store = ExplanationStore()
    return _default_store


def _build_explanation(
    explanation_id: str,
    entity_type: str,
    entity_id: str,
    mode: ExplanationMode,
    content: str,
    metadata: dict[str, Any],
    claim_requests: list[Any],
) -> ExplanationMetadata:
    return ExplanationMetadata(
        id=explanation_id,
        entity_type=entity_type,
        entity_id=entity_id,
        mode=mode,
        content=content,
        metadata=metadata,
        claims=[
            ExplanationClaim(
                claim_type=claim.claim_type,
                target=claim.target,
                expected=claim.expected,
                description=claim.description,
            )
            for claim in claim_requests
        ],
    )


@router.post("/", dependencies=[require_scope("workflows:write")], status_code=201)
async def create_explanation(
    request_body: ExplanationRequest, request: Request
) -> ExplanationMetadata:
    """Generate a new explanation scaffold for an entity."""
    explanation_id = f"expl-{uuid.uuid4().hex[:12]}"
    explanation = _build_explanation(
        explanation_id=explanation_id,
        entity_type=request_body.entity_type,
        entity_id=request_body.entity_id,
        mode=request_body.mode,
        content=_render_explanation_content(request_body),
        metadata=request_body.metadata,
        claim_requests=request_body.claims,
    )

    explanation.fact_check_status = await run_fact_check_hooks(explanation)
    _get_store(request).save(explanation)

    logger.info(
        "explanation_created",
        explanation_id=explanation_id,
        entity_type=request_body.entity_type,
        entity_id=request_body.entity_id,
        mode=request_body.mode,
        claims=len(explanation.claims),
        fact_check_status=explanation.fact_check_status,
    )
    return explanation


@router.get("/{explanation_id}", dependencies=[require_scope("workflows:read")])
async def get_explanation(explanation_id: str, request: Request) -> ExplanationMetadata:
    """Retrieve an explanation by ID."""
    explanation = _get_store(request).get(explanation_id)
    if explanation is None:
        raise HTTPException(status_code=404, detail=f"Explanation '{explanation_id}' not found")

    logger.info("explanation_retrieved", explanation_id=explanation_id)
    return explanation


@router.get("/", dependencies=[require_scope("workflows:read")])
async def list_explanations(
    request: Request,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> list[ExplanationMetadata]:
    """List explanations, optionally filtered by entity."""
    results = _get_store(request).list(entity_type=entity_type, entity_id=entity_id)

    logger.info(
        "explanations_listed",
        count=len(results),
        entity_type=entity_type,
        entity_id=entity_id,
    )
    return results


@router.post(
    "/{explanation_id}/fact-check",
    dependencies=[require_scope("workflows:write")],
)
async def rerun_fact_check(explanation_id: str, request: Request) -> ExplanationMetadata:
    """Re-run deterministic fact-check validation for an explanation."""
    store = _get_store(request)
    explanation = store.get(explanation_id)
    if explanation is None:
        raise HTTPException(status_code=404, detail=f"Explanation '{explanation_id}' not found")

    explanation.fact_check_status = await run_fact_check_hooks(explanation)
    store.save(explanation)

    logger.info(
        "explanation_fact_check_rerun",
        explanation_id=explanation_id,
        fact_check_status=explanation.fact_check_status,
    )
    return explanation


@router.get(
    "/{explanation_id}/claims",
    dependencies=[require_scope("workflows:read")],
)
async def get_explanation_claims(explanation_id: str, request: Request) -> list[ExplanationClaim]:
    """Retrieve deterministic fact-check claims for an explanation."""
    explanation = _get_store(request).get(explanation_id)
    if explanation is None:
        raise HTTPException(status_code=404, detail=f"Explanation '{explanation_id}' not found")
    return explanation.claims


@router.delete("/{explanation_id}", dependencies=[require_scope("workflows:write")])
async def delete_explanation(explanation_id: str, request: Request) -> dict[str, str]:
    """Delete an explanation."""
    deleted = _get_store(request).delete(explanation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Explanation '{explanation_id}' not found")

    logger.info("explanation_deleted", explanation_id=explanation_id)
    return {"message": f"Explanation '{explanation_id}' deleted"}


def get_explanations_store(request: Request | None = None) -> ExplanationStore:
    """Return the active store (used by test fixtures)."""
    return _get_store(request)


@router.post(
    "/diff-review",
    dependencies=[require_scope("workflows:write")],
    status_code=201,
)
async def create_diff_review(
    request_body: DiffReviewRequest, request: Request
) -> ExplanationMetadata:
    """Generate a diff review visual page."""
    explanation_id = f"expl-{uuid.uuid4().hex[:12]}"

    html_content = render_diff_review(
        entity_type=request_body.entity_type,
        entity_id=request_body.entity_id,
        diff_text=request_body.diff_text,
    )

    explanation = _build_explanation(
        explanation_id=explanation_id,
        entity_type=request_body.entity_type,
        entity_id=request_body.entity_id,
        mode=ExplanationMode.DIFF_REVIEW,
        content=html_content,
        metadata=request_body.metadata,
        claim_requests=request_body.claims,
    )

    explanation.fact_check_status = await run_fact_check_hooks(explanation)
    _get_store(request).save(explanation)

    logger.info(
        "diff_review_created",
        explanation_id=explanation_id,
        entity_type=request_body.entity_type,
        entity_id=request_body.entity_id,
        claims=len(explanation.claims),
        fact_check_status=explanation.fact_check_status,
    )
    return explanation


@router.post(
    "/plan-review",
    dependencies=[require_scope("workflows:write")],
    status_code=201,
)
async def create_plan_review(
    request_body: PlanReviewRequest, request: Request
) -> ExplanationMetadata:
    """Generate a plan review visual page."""
    explanation_id = f"expl-{uuid.uuid4().hex[:12]}"

    html_content = render_plan_review(
        entity_type=request_body.entity_type,
        entity_id=request_body.entity_id,
        plan_text=request_body.plan_text,
    )

    explanation = _build_explanation(
        explanation_id=explanation_id,
        entity_type=request_body.entity_type,
        entity_id=request_body.entity_id,
        mode=ExplanationMode.PLAN_REVIEW,
        content=html_content,
        metadata=request_body.metadata,
        claim_requests=request_body.claims,
    )

    explanation.fact_check_status = await run_fact_check_hooks(explanation)
    _get_store(request).save(explanation)

    logger.info(
        "plan_review_created",
        explanation_id=explanation_id,
        entity_type=request_body.entity_type,
        entity_id=request_body.entity_id,
        claims=len(explanation.claims),
        fact_check_status=explanation.fact_check_status,
    )
    return explanation


@router.post(
    "/project-recap",
    dependencies=[require_scope("workflows:write")],
    status_code=201,
)
async def create_project_recap(
    request_body: ProjectRecapRequest, request: Request
) -> ExplanationMetadata:
    """Generate a project recap visual page."""
    explanation_id = f"expl-{uuid.uuid4().hex[:12]}"

    html_content = render_project_recap(
        entity_type=request_body.entity_type,
        entity_id=request_body.entity_id,
        recap_text=request_body.recap_text,
        highlights=request_body.highlights,
    )

    explanation = _build_explanation(
        explanation_id=explanation_id,
        entity_type=request_body.entity_type,
        entity_id=request_body.entity_id,
        mode=ExplanationMode.PROJECT_RECAP,
        content=html_content,
        metadata=request_body.metadata,
        claim_requests=request_body.claims,
    )

    explanation.fact_check_status = await run_fact_check_hooks(explanation)
    _get_store(request).save(explanation)

    logger.info(
        "project_recap_created",
        explanation_id=explanation_id,
        entity_type=request_body.entity_type,
        entity_id=request_body.entity_id,
        claims=len(explanation.claims),
        fact_check_status=explanation.fact_check_status,
    )
    return explanation


def _render_explanation_content(request: ExplanationRequest) -> str:
    title = f"{request.mode.value.replace('_', ' ').title()} explanation"
    sections = [
        title,
        f"Entity: {request.entity_type} '{request.entity_id}'",
    ]
    highlights = request.metadata.get("highlights", [])
    if isinstance(highlights, list) and highlights:
        sections.append("Highlights:")
        sections.extend(f"- {item}" for item in highlights if isinstance(item, str))
    return "\n".join(sections)
