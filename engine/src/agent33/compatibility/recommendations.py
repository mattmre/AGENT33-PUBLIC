"""Resource recommendations from compatibility history."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent33.compatibility.reports import CompatibilityOutcome, CompatibilityReportStore
from agent33.resources.manifest import ResourceManifest  # noqa: TC001
from agent33.resources.service import ResourceService  # noqa: TC001


class ResourceRecommendation(BaseModel):
    resource: ResourceManifest
    score: int
    reasons: list[str] = Field(default_factory=list)


class ResourceRecommendationResult(BaseModel):
    items: list[ResourceRecommendation] = Field(default_factory=list)


def recommend_resources(
    *,
    resource_service: ResourceService,
    reports: CompatibilityReportStore,
    query: str = "",
    model: str = "",
    provider: str = "",
    limit: int = 10,
) -> ResourceRecommendationResult:
    search = resource_service.search(query=query, limit=100)
    recommendations = [
        _score_resource(resource, reports=reports, model=model, provider=provider)
        for resource in search.items
    ]
    recommendations.sort(key=lambda item: item.score, reverse=True)
    return ResourceRecommendationResult(items=recommendations[: max(1, limit)])


def _score_resource(
    resource: ResourceManifest,
    *,
    reports: CompatibilityReportStore,
    model: str,
    provider: str,
) -> ResourceRecommendation:
    score = 50
    reasons: list[str] = []
    if resource.trust.verified:
        score += 10
        reasons.append("verified publisher")
    if resource.rollback.supported:
        score += 5
        reasons.append("rollback available")
    matches = reports.list_reports(
        model=model,
        provider=provider,
        resource_id=resource.id,
        limit=50,
    )
    success_count = sum(1 for report in matches if report.outcome == CompatibilityOutcome.SUCCESS)
    degraded_count = sum(
        1 for report in matches if report.outcome == CompatibilityOutcome.DEGRADED
    )
    failure_count = sum(1 for report in matches if report.outcome == CompatibilityOutcome.FAILED)
    score += success_count * 12
    score -= degraded_count * 6
    score -= failure_count * 18
    if success_count:
        reasons.append("compatible success history")
    if degraded_count:
        reasons.append("degraded compatibility history")
    if failure_count:
        reasons.append("failed compatibility history")
    return ResourceRecommendation(
        resource=resource,
        score=score,
        reasons=reasons or ["no compatibility history yet"],
    )
