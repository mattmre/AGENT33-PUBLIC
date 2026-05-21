"""Completion gate preview routes."""

from __future__ import annotations

from fastapi import APIRouter

from agent33.ops.completion_gate import (
    CompletionGateInput,
    CompletionGateResult,
    evaluate_completion_gate,
)
from agent33.security.permissions import require_scope

router = APIRouter(prefix="/v1/completion-gates", tags=["completion-gates"])


@router.post("/preview", dependencies=[require_scope("workflows:read")])
async def preview_completion_gate(request: CompletionGateInput) -> CompletionGateResult:
    """Evaluate completion readiness for a run without mutating run state."""
    return evaluate_completion_gate(request)
