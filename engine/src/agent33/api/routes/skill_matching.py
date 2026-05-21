"""FastAPI router for hybrid skill matching calibration (S29)."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from agent33.security.permissions import require_scope
from agent33.skills.calibration import (
    HybridSkillMatcher,
    MatchDiagnostics,
    MatchResult,
    MatchThresholds,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/v1/skills", tags=["skill-matching"])

# Module-level matcher reference (set during lifespan or tests)
_skill_matcher: HybridSkillMatcher | None = None


def set_skill_matcher(matcher: HybridSkillMatcher | None) -> None:
    """Set the module-level hybrid skill matcher reference."""
    global _skill_matcher  # noqa: PLW0603
    _skill_matcher = matcher


def _get_matcher(request: Request) -> HybridSkillMatcher:
    """Resolve the hybrid skill matcher from the test override or app state."""
    if _skill_matcher is not None:
        return _skill_matcher
    svc: Any = getattr(request.app.state, "hybrid_skill_matcher", None)
    if svc is not None:
        return svc  # type: ignore[no-any-return]
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Hybrid skill matcher not initialized",
    )


# -- Request / Response models --


class MatchRequest(BaseModel):
    """Body for the skill match endpoint."""

    query: str = Field(..., min_length=1, max_length=500)
    context: dict[str, Any] | None = None


class DiagnosticsRequest(BaseModel):
    """Body for the diagnostics endpoint."""

    query: str = Field(..., min_length=1, max_length=500)


class CalibrateRequest(BaseModel):
    """Body for the calibration endpoint."""

    test_queries: list[dict[str, Any]] = Field(..., min_length=1)


class ThresholdCompareRequest(BaseModel):
    """Body for the threshold comparison endpoint."""

    queries: list[dict[str, Any]] = Field(..., min_length=1)
    threshold_a: MatchThresholds
    threshold_b: MatchThresholds


# -- Routes --


@router.post(
    "/match",
    response_model=MatchResult,
    dependencies=[require_scope("agents:read")],
)
async def match_skills(
    request: Request,
    body: MatchRequest,
) -> MatchResult:
    """Match a query to skills using the 4-stage hybrid pipeline."""
    matcher = _get_matcher(request)
    return matcher.match(body.query, context=body.context)


@router.get(
    "/match/thresholds",
    response_model=MatchThresholds,
    dependencies=[require_scope("agents:read")],
)
async def get_thresholds(request: Request) -> MatchThresholds:
    """Return current matching thresholds."""
    matcher = _get_matcher(request)
    return matcher.thresholds


@router.put(
    "/match/thresholds",
    response_model=MatchThresholds,
    dependencies=[require_scope("admin")],
)
async def update_thresholds(
    request: Request,
    body: MatchThresholds,
) -> MatchThresholds:
    """Update matching thresholds (admin only)."""
    matcher = _get_matcher(request)
    matcher.thresholds = body
    logger.info("skill_match_thresholds_updated", thresholds=body.model_dump())
    return matcher.thresholds


@router.post(
    "/match/diagnostics",
    response_model=list[MatchDiagnostics],
    dependencies=[require_scope("agents:read")],
)
async def run_diagnostics(
    request: Request,
    body: DiagnosticsRequest,
) -> list[MatchDiagnostics]:
    """Run diagnostics on a query, returning per-stage analysis."""
    matcher = _get_matcher(request)
    return matcher.get_diagnostics(body.query)


@router.post(
    "/match/calibrate",
    dependencies=[require_scope("admin")],
)
async def calibrate(
    request: Request,
    body: CalibrateRequest,
) -> dict[str, Any]:
    """Calibrate thresholds using test queries (admin only)."""
    matcher = _get_matcher(request)
    return matcher.calibrate(body.test_queries)


@router.post(
    "/match/compare",
    dependencies=[require_scope("admin")],
)
async def compare_thresholds(
    request: Request,
    body: ThresholdCompareRequest,
) -> dict[str, Any]:
    """A/B compare two threshold configurations (admin only)."""
    matcher = _get_matcher(request)
    return matcher.compare_thresholds(body.queries, body.threshold_a, body.threshold_b)
