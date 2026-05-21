"""Compatibility-aware model routing preview."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent33.compatibility.reports import (
    CompatibilityOutcome,
    CompatibilityReportStore,
)


class ModelRouteCandidate(BaseModel):
    provider: str
    model: str
    context_length: int = Field(default=0, ge=0)
    cost_rank: int = Field(default=5, ge=1)
    healthy: bool = True


class CompatibilityRouteRequest(BaseModel):
    task_risk: str = "normal"
    resource_id: str = ""
    required_context: int = Field(default=0, ge=0)
    candidates: list[ModelRouteCandidate] = Field(default_factory=list)


class CompatibilityRouteDecision(BaseModel):
    provider: str
    model: str
    score: int
    reasons: list[str] = Field(default_factory=list)


def choose_compatible_route(
    request: CompatibilityRouteRequest,
    *,
    reports: CompatibilityReportStore,
) -> CompatibilityRouteDecision:
    scored = [_score_candidate(candidate, request, reports) for candidate in request.candidates]
    if not scored:
        return CompatibilityRouteDecision(
            provider="",
            model="",
            score=0,
            reasons=["No route candidates supplied."],
        )
    scored.sort(key=lambda item: item.score, reverse=True)
    return scored[0]


def _score_candidate(
    candidate: ModelRouteCandidate,
    request: CompatibilityRouteRequest,
    reports: CompatibilityReportStore,
) -> CompatibilityRouteDecision:
    score = 100
    reasons: list[str] = []
    if not candidate.healthy:
        score -= 50
        reasons.append("provider unhealthy")
    if request.required_context and candidate.context_length < request.required_context:
        score -= 35
        reasons.append("context too small")
    score -= candidate.cost_rank

    prior_reports = reports.list_reports(
        model=candidate.model,
        provider=candidate.provider,
        resource_id=request.resource_id,
        limit=25,
    )
    failures = [
        report for report in prior_reports if report.outcome == CompatibilityOutcome.FAILED
    ]
    successes = [
        report for report in prior_reports if report.outcome == CompatibilityOutcome.SUCCESS
    ]
    degraded = [
        report for report in prior_reports if report.outcome == CompatibilityOutcome.DEGRADED
    ]
    score -= len(failures) * 20
    score -= len(degraded) * 8
    score += len(successes) * 10
    if failures:
        reasons.append("prior failures")
    if degraded:
        reasons.append("prior degraded runs")
    if successes:
        reasons.append("prior successful runs")
    if request.task_risk in {"high", "critical"} and not successes:
        score -= 15
        reasons.append("high-risk task lacks success history")

    return CompatibilityRouteDecision(
        provider=candidate.provider,
        model=candidate.model,
        score=score,
        reasons=reasons or ["lowest risk available route"],
    )
