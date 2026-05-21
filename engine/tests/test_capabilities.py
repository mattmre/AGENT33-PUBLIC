from __future__ import annotations

from agent33.policy.capabilities import (
    ActionRisk,
    AuthorityLevel,
    CapabilityGrant,
    allows_action,
    classify_action_risk,
)


def test_capability_grant_allows_actions_within_authority_and_risk() -> None:
    grant = CapabilityGrant(
        subject="agent",
        capability="filesystem",
        authority=AuthorityLevel.APPROVED_WRITE,
        risk_limit=ActionRisk.MEDIUM,
    )

    assert allows_action(
        grant,
        required_authority=AuthorityLevel.DRY_RUN,
        action_risk=ActionRisk.LOW,
    )
    assert not allows_action(
        grant,
        required_authority=AuthorityLevel.ADMIN,
        action_risk=ActionRisk.LOW,
    )
    assert not allows_action(
        grant,
        required_authority=AuthorityLevel.APPROVED_WRITE,
        action_risk=ActionRisk.HIGH,
    )


def test_classify_action_risk_marks_irreversible_and_high_risk_actions() -> None:
    assert classify_action_risk("delete production credential") == ActionRisk.IRREVERSIBLE
    assert classify_action_risk("resource install") == ActionRisk.HIGH
    assert classify_action_risk("apply patch") == ActionRisk.MEDIUM
    assert classify_action_risk("read catalog") == ActionRisk.LOW
