"""Marketplace curation: state machine, quality assessment, and curation records.

Follows the state machine pattern from ``review/state_machine.py`` and the
quality scoring pattern from ``improvement/quality.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agent33.packs.manifest import PackManifest
    from agent33.packs.provenance_models import PackProvenance

# ---------------------------------------------------------------------------
# Curation status enum
# ---------------------------------------------------------------------------


class CurationStatus(StrEnum):
    """Lifecycle states for marketplace pack curation."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    LISTED = "listed"
    FEATURED = "featured"
    DEPRECATED = "deprecated"
    UNLISTED = "unlisted"


# ---------------------------------------------------------------------------
# Transition table
# ---------------------------------------------------------------------------

_VALID_TRANSITIONS: dict[CurationStatus, frozenset[CurationStatus]] = {
    CurationStatus.DRAFT: frozenset({CurationStatus.SUBMITTED}),
    CurationStatus.SUBMITTED: frozenset({CurationStatus.UNDER_REVIEW}),
    CurationStatus.UNDER_REVIEW: frozenset(
        {CurationStatus.APPROVED, CurationStatus.CHANGES_REQUESTED}
    ),
    CurationStatus.CHANGES_REQUESTED: frozenset({CurationStatus.SUBMITTED}),
    CurationStatus.APPROVED: frozenset({CurationStatus.LISTED}),
    CurationStatus.LISTED: frozenset(
        {CurationStatus.FEATURED, CurationStatus.DEPRECATED, CurationStatus.UNLISTED}
    ),
    CurationStatus.FEATURED: frozenset(
        {CurationStatus.LISTED, CurationStatus.DEPRECATED, CurationStatus.UNLISTED}
    ),
    CurationStatus.DEPRECATED: frozenset({CurationStatus.UNLISTED}),
    CurationStatus.UNLISTED: frozenset({CurationStatus.SUBMITTED}),
}


class InvalidCurationTransitionError(Exception):
    """Raised when a curation state transition is not allowed."""

    def __init__(self, from_state: CurationStatus, to_state: CurationStatus) -> None:
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"Invalid transition: {from_state.value} -> {to_state.value}")


class CurationStateMachine:
    """Enforce valid state transitions for curation records."""

    @staticmethod
    def can_transition(from_state: CurationStatus, to_state: CurationStatus) -> bool:
        """Return ``True`` if the transition is valid."""
        allowed = _VALID_TRANSITIONS.get(from_state, frozenset())
        return to_state in allowed

    @staticmethod
    def valid_next_states(state: CurationStatus) -> frozenset[CurationStatus]:
        """Return the set of states reachable from *state*."""
        return _VALID_TRANSITIONS.get(state, frozenset())

    @staticmethod
    def transition(from_state: CurationStatus, to_state: CurationStatus) -> CurationStatus:
        """Attempt a transition; raise on invalid."""
        if not CurationStateMachine.can_transition(from_state, to_state):
            raise InvalidCurationTransitionError(from_state, to_state)
        return to_state


# ---------------------------------------------------------------------------
# Quality assessment models
# ---------------------------------------------------------------------------


class QualityCheck(BaseModel):
    """A single quality dimension check result."""

    name: str
    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    reason: str = ""


class QualityAssessment(BaseModel):
    """Aggregate quality score for a pack."""

    overall_score: float = Field(ge=0.0, le=1.0)
    label: str = ""  # "low" | "medium" | "high"
    checks: list[QualityCheck] = Field(default_factory=list)
    passed: bool = False
    assessed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CurationQualitySignal(BaseModel):
    """Operator-facing signal used during registry review."""

    id: str
    severity: str
    message: str
    action: str
    evidence: str = ""


class CurationReviewSignals(BaseModel):
    """Aggregated curation signals for marketplace review and featuring."""

    pack_name: str
    quality_label: str
    quality_score: float = Field(ge=0.0, le=1.0)
    risk_level: str
    publish_blockers: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    signals: list[CurationQualitySignal] = Field(default_factory=list)
    featured_eligible: bool = False
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def assess_pack_quality(
    manifest: PackManifest,
    provenance: PackProvenance | None = None,
    *,
    threshold: float = 0.5,
) -> QualityAssessment:
    """Score a pack manifest against weighted quality dimensions.

    Dimensions and weights:
      description_quality (0.20) -- description length >= 50 chars
      tags_present (0.15)        -- at least 2 tags
      category_assigned (0.15)   -- non-empty category
      license_present (0.10)     -- non-empty license
      author_present (0.10)      -- non-empty author
      skills_count (0.15)        -- at least 1 skill
      provenance_signed (0.15)   -- has provenance metadata
    """
    checks: list[QualityCheck] = []

    # description_quality
    desc_len = len(manifest.description.strip())
    desc_score = min(1.0, desc_len / 50.0)
    checks.append(
        QualityCheck(
            name="description_quality",
            passed=desc_len >= 50,
            score=round(desc_score, 3),
            reason=f"description length: {desc_len} chars",
        )
    )

    # tags_present
    tag_count = len(manifest.tags)
    tags_score = min(1.0, tag_count / 2.0)
    checks.append(
        QualityCheck(
            name="tags_present",
            passed=tag_count >= 2,
            score=round(tags_score, 3),
            reason=f"{tag_count} tag(s) present",
        )
    )

    # category_assigned
    has_category = bool(manifest.category.strip())
    checks.append(
        QualityCheck(
            name="category_assigned",
            passed=has_category,
            score=1.0 if has_category else 0.0,
            reason="category assigned" if has_category else "no category",
        )
    )

    # license_present
    has_license = bool(manifest.license.strip())
    checks.append(
        QualityCheck(
            name="license_present",
            passed=has_license,
            score=1.0 if has_license else 0.0,
            reason="license present" if has_license else "no license",
        )
    )

    # author_present
    has_author = bool(manifest.author.strip())
    checks.append(
        QualityCheck(
            name="author_present",
            passed=has_author,
            score=1.0 if has_author else 0.0,
            reason="author present" if has_author else "no author",
        )
    )

    # skills_count
    skill_count = len(manifest.skills)
    skills_score = min(1.0, float(skill_count))
    checks.append(
        QualityCheck(
            name="skills_count",
            passed=skill_count >= 1,
            score=round(skills_score, 3),
            reason=f"{skill_count} skill(s)",
        )
    )

    # provenance_signed
    has_provenance = provenance is not None
    checks.append(
        QualityCheck(
            name="provenance_signed",
            passed=has_provenance,
            score=1.0 if has_provenance else 0.0,
            reason="provenance present" if has_provenance else "no provenance",
        )
    )

    # Weighted scoring
    weights: dict[str, float] = {
        "description_quality": 0.20,
        "tags_present": 0.15,
        "category_assigned": 0.15,
        "license_present": 0.10,
        "author_present": 0.10,
        "skills_count": 0.15,
        "provenance_signed": 0.15,
    }

    check_map = {c.name: c.score for c in checks}
    overall = sum(check_map[name] * weight for name, weight in weights.items())
    overall = round(min(1.0, max(0.0, overall)), 3)

    label = "low"
    if overall >= 0.70:
        label = "high"
    elif overall >= 0.45:
        label = "medium"

    return QualityAssessment(
        overall_score=overall,
        label=label,
        checks=checks,
        passed=overall >= threshold,
    )


def build_curation_review_signals(
    manifest: PackManifest,
    assessment: QualityAssessment,
    provenance: PackProvenance | None = None,
) -> CurationReviewSignals:
    """Convert quality checks into review blockers, actions, and feature eligibility."""
    signals: list[CurationQualitySignal] = []
    blockers: list[str] = []
    recommendations: list[str] = []
    check_map = {check.name: check for check in assessment.checks}

    for check in assessment.checks:
        if check.passed:
            continue
        severity = "warning"
        if check.name in {"skills_count", "provenance_signed"}:
            severity = "blocker"
            blockers.append(check.name)
        elif check.score < 0.5:
            blockers.append(check.name)
        action = _quality_action_for_check(check.name)
        recommendations.append(action)
        signals.append(
            CurationQualitySignal(
                id=check.name,
                severity=severity,
                message=check.reason,
                action=action,
                evidence=f"score={check.score}",
            )
        )

    if not assessment.passed:
        blockers.append("minimum_quality_threshold")
        recommendations.append("Raise quality score above the marketplace threshold.")

    if provenance is None:
        recommendations.append("Attach signed provenance before public listing.")

    risk_level = "low"
    if blockers:
        has_blocker_signal = any(signal.severity == "blocker" for signal in signals)
        risk_level = "high" if has_blocker_signal else "medium"
    elif assessment.overall_score < 0.7:
        risk_level = "medium"

    featured_eligible = (
        assessment.overall_score >= 0.85
        and provenance is not None
        and bool(manifest.category.strip())
        and len(manifest.tags) >= 2
        and not blockers
    )

    if featured_eligible:
        recommendations.append("Eligible for featured review.")
    elif check_map.get("description_quality") and not check_map["description_quality"].passed:
        recommendations.append("Improve operator-facing description before featuring.")

    return CurationReviewSignals(
        pack_name=manifest.name,
        quality_label=assessment.label,
        quality_score=assessment.overall_score,
        risk_level=risk_level,
        publish_blockers=sorted(set(blockers)),
        recommendations=_dedupe(recommendations),
        signals=signals,
        featured_eligible=featured_eligible,
    )


def _quality_action_for_check(check_name: str) -> str:
    return {
        "description_quality": "Expand the pack description with outcome, setup, and limits.",
        "tags_present": "Add at least two discovery tags.",
        "category_assigned": "Assign a marketplace category.",
        "license_present": "Declare the pack license.",
        "author_present": "Declare the pack author or owning team.",
        "skills_count": "Bundle at least one loadable skill.",
        "provenance_signed": "Attach signed provenance metadata.",
    }.get(check_name, "Resolve the failed quality check.")


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


# ---------------------------------------------------------------------------
# Curation record
# ---------------------------------------------------------------------------


class CurationRecord(BaseModel):
    """Tracks the curation lifecycle of a pack in the marketplace."""

    pack_name: str
    version: str = ""
    status: CurationStatus = CurationStatus.DRAFT
    quality: QualityAssessment | None = None
    review_signals: CurationReviewSignals | None = None
    badges: list[str] = Field(default_factory=list)
    featured: bool = False
    verified: bool = False
    reviewer_id: str = ""
    review_notes: str = ""
    deprecation_reason: str = ""
    submitted_at: datetime | None = None
    reviewed_at: datetime | None = None
    listed_at: datetime | None = None
    download_count: int = 0
