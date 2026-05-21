"""Risk assessment engine.

Determines the risk level for a change set based on identified triggers,
following the risk matrix in ``core/orchestrator/TWO_LAYER_REVIEW.md``.
"""

from __future__ import annotations

from agent33.review.models import RiskAssessment, RiskLevel, RiskTrigger

# ---------------------------------------------------------------------------
# Trigger → risk-level mapping
# ---------------------------------------------------------------------------

_TRIGGER_RISK: dict[RiskTrigger, RiskLevel] = {
    RiskTrigger.DOCUMENTATION: RiskLevel.NONE,
    RiskTrigger.CONFIG: RiskLevel.LOW,
    RiskTrigger.CODE_ISOLATED: RiskLevel.LOW,
    RiskTrigger.API_INTERNAL: RiskLevel.MEDIUM,
    RiskTrigger.API_PUBLIC: RiskLevel.HIGH,
    RiskTrigger.SECURITY: RiskLevel.HIGH,
    RiskTrigger.SCHEMA: RiskLevel.HIGH,
    RiskTrigger.INFRASTRUCTURE: RiskLevel.HIGH,
    RiskTrigger.PROMPT_AGENT: RiskLevel.HIGH,
    RiskTrigger.SECRETS: RiskLevel.CRITICAL,
    RiskTrigger.PRODUCTION_DATA: RiskLevel.CRITICAL,
    RiskTrigger.PROMPT_INJECTION: RiskLevel.HIGH,
    RiskTrigger.SANDBOX_ESCAPE: RiskLevel.HIGH,
    RiskTrigger.SUPPLY_CHAIN: RiskLevel.HIGH,
}

# Risk-level ordinal for comparison
_RISK_ORD: dict[RiskLevel, int] = {
    RiskLevel.NONE: 0,
    RiskLevel.LOW: 1,
    RiskLevel.MEDIUM: 2,
    RiskLevel.HIGH: 3,
    RiskLevel.CRITICAL: 4,
}


class RiskAssessor:
    """Evaluate a set of triggers and return a :class:`RiskAssessment`."""

    def assess(self, triggers: list[RiskTrigger]) -> RiskAssessment:
        """Determine risk level from identified triggers.

        Rules (from TWO_LAYER_REVIEW.md):
        - Use the **highest** applicable risk level.
        - None  → no review required.
        - Low   → L1 required.
        - Medium → L1 + L2 (agent) required.
        - High  → L1 + L2 (human) required.
        - Critical → L1 + designated human approver.
        """
        if not triggers:
            return RiskAssessment(
                risk_level=RiskLevel.NONE,
                triggers_identified=[],
                l1_required=False,
                l2_required=False,
            )

        max_level = RiskLevel.NONE
        for trigger in triggers:
            level = _TRIGGER_RISK.get(trigger, RiskLevel.LOW)
            if _RISK_ORD[level] > _RISK_ORD[max_level]:
                max_level = level

        l1_required = _RISK_ORD[max_level] >= _RISK_ORD[RiskLevel.LOW]
        l2_required = _RISK_ORD[max_level] >= _RISK_ORD[RiskLevel.MEDIUM]

        return RiskAssessment(
            risk_level=max_level,
            triggers_identified=list(triggers),
            l1_required=l1_required,
            l2_required=l2_required,
        )
