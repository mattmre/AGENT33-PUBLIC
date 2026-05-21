"""FastAPI router for sandbox review operations."""

from __future__ import annotations

from fastapi import APIRouter

from agent33.sandboxing.review import SandboxReview, sandbox_review_summary
from agent33.security.permissions import require_scope

router = APIRouter(prefix="/v1/sandboxing", tags=["sandboxing"])


@router.post("/review", dependencies=[require_scope("admin:read")])
async def review_sandbox(review: SandboxReview) -> dict[str, object]:
    """Evaluate a sandbox surface and return a review summary."""
    return sandbox_review_summary(review)
