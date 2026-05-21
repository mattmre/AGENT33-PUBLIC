"""Capability grants and action risk classification."""

from __future__ import annotations

from enum import IntEnum, StrEnum

from pydantic import BaseModel


class AuthorityLevel(IntEnum):
    READ_ONLY = 1
    DRY_RUN = 2
    APPROVED_WRITE = 3
    ADMIN = 4


class ActionRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    IRREVERSIBLE = "irreversible"


class CapabilityGrant(BaseModel):
    subject: str
    capability: str
    authority: AuthorityLevel = AuthorityLevel.READ_ONLY
    risk_limit: ActionRisk = ActionRisk.LOW
    scope: str = ""


_RISK_ORDER = {
    ActionRisk.LOW: 1,
    ActionRisk.MEDIUM: 2,
    ActionRisk.HIGH: 3,
    ActionRisk.IRREVERSIBLE: 4,
}


def allows_action(
    grant: CapabilityGrant,
    *,
    required_authority: AuthorityLevel,
    action_risk: ActionRisk,
) -> bool:
    return (
        grant.authority >= required_authority
        and _RISK_ORDER[grant.risk_limit] >= _RISK_ORDER[action_risk]
    )


def classify_action_risk(action: str) -> ActionRisk:
    normalized = action.lower()
    if any(term in normalized for term in ["delete", "drop", "credential", "deploy"]):
        return ActionRisk.IRREVERSIBLE
    if any(term in normalized for term in ["migration", "external_write", "install"]):
        return ActionRisk.HIGH
    if any(term in normalized for term in ["write", "patch", "update"]):
        return ActionRisk.MEDIUM
    return ActionRisk.LOW
