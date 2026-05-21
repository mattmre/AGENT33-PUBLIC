"""Helpers for converting repository harvest data into improvement records."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent33.improvement.models import (
    IntakeClassification,
    IntakeContent,
    IntakeRelevance,
    ResearchIntake,
)


class RepoHarvestRecord(BaseModel):
    """Repository metadata harvested from a source query."""

    rank: int = Field(ge=1)
    full_name: str
    url: str
    stars: int = Field(default=0, ge=0)
    source_query: str = ""


class FeatureCandidateInput(BaseModel):
    """Raw feature-candidate signal from competitive research."""

    feature_name: str
    category: str = ""
    source_repo: str = ""
    evidence_path: str = ""
    maturity: str = ""
    security_impact: str = ""
    implementation_hint: str = ""
    impact_score: float = Field(ge=1.0, le=10.0)
    feasibility_score: float = Field(ge=1.0, le=10.0)
    risk_score: float = Field(ge=1.0, le=10.0)


class ScoredFeatureCandidate(FeatureCandidateInput):
    """Feature candidate enriched with weighted priority score."""

    weighted_priority: float


def _priority_from_rank(rank: int) -> int:
    """Map repository rank (1-30) into a discrete priority bucket (1-10)."""
    clamped_rank = max(1, min(rank, 30))
    bucket = (clamped_rank - 1) // 3  # 0–9
    return 10 - bucket


def build_competitive_intake(
    record: RepoHarvestRecord,
    submitted_by: str,
    tenant_id: str,
) -> ResearchIntake:
    """Convert repository harvest metadata into a competitive research intake."""
    return ResearchIntake(
        submitted_by=submitted_by,
        tenant_id=tenant_id,
        classification=IntakeClassification(
            research_type="competitive",
            category="repository_scan",
            urgency="medium",
        ),
        content=IntakeContent(
            title=f"Competitive repository: {record.full_name}",
            summary=(
                f"Harvested repo rank #{record.rank} with {record.stars} stars "
                f"from query '{record.source_query}'."
            ),
            source=record.url,
        ),
        relevance=IntakeRelevance(
            impact_areas=["competitive-intelligence", "feature-discovery"],
            priority_score=_priority_from_rank(record.rank),
        ),
    )


def score_feature_candidate(candidate: FeatureCandidateInput) -> ScoredFeatureCandidate:
    """Compute weighted feature candidate priority."""
    weighted_priority = round(
        0.5 * candidate.impact_score
        + 0.3 * candidate.feasibility_score
        + 0.2 * (11 - candidate.risk_score),
        3,
    )
    return ScoredFeatureCandidate(
        **candidate.model_dump(),
        weighted_priority=weighted_priority,
    )


def prioritize_feature_candidates(
    candidates: list[FeatureCandidateInput],
    top_n: int,
) -> list[ScoredFeatureCandidate]:
    """Score and return highest-priority feature candidates."""
    if top_n <= 0:
        return []
    scored = [score_feature_candidate(candidate) for candidate in candidates]
    scored.sort(key=lambda candidate: candidate.weighted_priority, reverse=True)
    return scored[:top_n]
