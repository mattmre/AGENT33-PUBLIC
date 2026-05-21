"""Reviewer assignment engine.

Maps change types to reviewer roles using the assignment matrix defined in
``core/orchestrator/TWO_LAYER_REVIEW.md``.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent33.review.models import RiskTrigger

# ---------------------------------------------------------------------------
# Assignment result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReviewerAssignment:
    """Recommended reviewer for a single layer."""

    reviewer_role: str
    agent_id: str  # e.g. "AGT-006"
    human_required: bool = False


# ---------------------------------------------------------------------------
# Assignment matrix (from TWO_LAYER_REVIEW.md § Reviewer Role Matrix)
# ---------------------------------------------------------------------------

# Grouped by primary trigger category → (L1 assignment, L2 assignment)
_ASSIGNMENT_MATRIX: dict[
    RiskTrigger,
    tuple[ReviewerAssignment, ReviewerAssignment],
] = {
    RiskTrigger.CODE_ISOLATED: (
        ReviewerAssignment("implementer", "AGT-006"),
        ReviewerAssignment("architect", "AGT-003"),
    ),
    RiskTrigger.SECURITY: (
        ReviewerAssignment("security", "AGT-004"),
        ReviewerAssignment("security-human", "HUMAN", human_required=True),
    ),
    RiskTrigger.PROMPT_INJECTION: (
        ReviewerAssignment("security", "AGT-004"),
        ReviewerAssignment("security-human", "HUMAN", human_required=True),
    ),
    RiskTrigger.SANDBOX_ESCAPE: (
        ReviewerAssignment("security", "AGT-004"),
        ReviewerAssignment("security-human", "HUMAN", human_required=True),
    ),
    RiskTrigger.SCHEMA: (
        ReviewerAssignment("implementer", "AGT-006"),
        ReviewerAssignment("architect", "AGT-003"),
    ),
    RiskTrigger.API_INTERNAL: (
        ReviewerAssignment("implementer", "AGT-006"),
        ReviewerAssignment("architect", "AGT-003"),
    ),
    RiskTrigger.API_PUBLIC: (
        ReviewerAssignment("implementer", "AGT-006"),
        ReviewerAssignment("architect-human", "HUMAN", human_required=True),
    ),
    RiskTrigger.INFRASTRUCTURE: (
        ReviewerAssignment("implementer", "AGT-006"),
        ReviewerAssignment("architect-human", "HUMAN", human_required=True),
    ),
    RiskTrigger.PROMPT_AGENT: (
        ReviewerAssignment("qa", "AGT-005"),
        ReviewerAssignment("orchestrator", "AGT-001"),
    ),
    RiskTrigger.DOCUMENTATION: (
        ReviewerAssignment("documentation", "AGT-007"),
        ReviewerAssignment("orchestrator", "AGT-001"),
    ),
    RiskTrigger.CONFIG: (
        ReviewerAssignment("implementer", "AGT-006"),
        ReviewerAssignment("architect", "AGT-003"),
    ),
    RiskTrigger.SECRETS: (
        ReviewerAssignment("security", "AGT-004"),
        ReviewerAssignment("security-human", "HUMAN", human_required=True),
    ),
    RiskTrigger.PRODUCTION_DATA: (
        ReviewerAssignment("security", "AGT-004"),
        ReviewerAssignment("security-human", "HUMAN", human_required=True),
    ),
    RiskTrigger.SUPPLY_CHAIN: (
        ReviewerAssignment("security", "AGT-004"),
        ReviewerAssignment("architect", "AGT-003"),
    ),
}

# Default assignment when trigger category has no explicit mapping
_DEFAULT_L1 = ReviewerAssignment("implementer", "AGT-006")
_DEFAULT_L2 = ReviewerAssignment("architect", "AGT-003")


class ReviewerAssigner:
    """Select reviewers for L1 and L2 based on change triggers."""

    def assign(
        self,
        triggers: list[RiskTrigger],
    ) -> tuple[ReviewerAssignment, ReviewerAssignment]:
        """Return ``(l1_reviewer, l2_reviewer)`` for the given triggers.

        Selection strategy:
        1. Pick the **highest-risk** trigger (same ordinal as risk assessor).
        2. Look up the assignment matrix for that trigger.
        3. If human review is required for L2, set ``human_required=True``.
        """
        if not triggers:
            return _DEFAULT_L1, _DEFAULT_L2

        from agent33.review.risk import _RISK_ORD, _TRIGGER_RISK

        # Find highest-risk trigger
        highest = triggers[0]
        for trigger in triggers[1:]:
            t_level = _TRIGGER_RISK.get(trigger, RiskTrigger.CONFIG)
            h_level = _TRIGGER_RISK.get(highest, RiskTrigger.CONFIG)
            if _RISK_ORD.get(t_level, 0) > _RISK_ORD.get(h_level, 0):  # type: ignore[arg-type]
                highest = trigger

        l1, l2 = _ASSIGNMENT_MATRIX.get(highest, (_DEFAULT_L1, _DEFAULT_L2))
        return l1, l2
