"""Unit tests for repository ingestion and feature candidate prioritization."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent33.improvement.repo_ingestion import (
    FeatureCandidateInput,
    RepoHarvestRecord,
    build_competitive_intake,
    prioritize_feature_candidates,
    score_feature_candidate,
)


def test_build_competitive_intake_maps_repo_record():
    record = RepoHarvestRecord(
        rank=1,
        full_name="org/project",
        url="https://github.com/org/project",
        stars=42000,
        source_query="agent framework",
    )

    intake = build_competitive_intake(record, submitted_by="harvester", tenant_id="tenant-a")

    assert intake.classification.research_type == "competitive"
    assert intake.classification.category == "repository_scan"
    assert intake.content.title == "Competitive repository: org/project"
    assert intake.content.source == "https://github.com/org/project"
    assert intake.submitted_by == "harvester"
    assert intake.tenant_id == "tenant-a"
    assert intake.relevance.priority_score == 10


def test_score_feature_candidate_uses_weighted_formula():
    candidate = FeatureCandidateInput(
        feature_name="Adaptive Orchestration",
        category="workflow",
        source_repo="org/project",
        evidence_path="README.md#features",
        maturity="beta",
        security_impact="medium",
        implementation_hint="start with planner plugin",
        impact_score=9,
        feasibility_score=7,
        risk_score=4,
    )

    scored = score_feature_candidate(candidate)

    assert scored.weighted_priority == 8.0


def test_prioritize_feature_candidates_sorts_and_limits():
    candidates = [
        FeatureCandidateInput(
            feature_name="Feature A",
            impact_score=8,
            feasibility_score=8,
            risk_score=3,
        ),
        FeatureCandidateInput(
            feature_name="Feature B",
            impact_score=7,
            feasibility_score=6,
            risk_score=8,
        ),
        FeatureCandidateInput(
            feature_name="Feature C",
            impact_score=10,
            feasibility_score=9,
            risk_score=2,
        ),
    ]

    prioritized = prioritize_feature_candidates(candidates, top_n=2)

    assert len(prioritized) == 2
    assert prioritized[0].feature_name == "Feature C"
    assert prioritized[1].feature_name == "Feature A"


def test_repo_harvest_record_rejects_non_positive_rank():
    with pytest.raises(ValidationError):
        RepoHarvestRecord(
            rank=0,
            full_name="org/project",
            url="https://github.com/org/project",
        )


def test_feature_candidate_rejects_out_of_range_scores():
    with pytest.raises(ValidationError):
        FeatureCandidateInput(
            feature_name="Out of range",
            impact_score=11,
            feasibility_score=7,
            risk_score=4,
        )
