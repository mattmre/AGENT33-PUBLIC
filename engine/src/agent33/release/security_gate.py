"""Component security gate evaluation for release checklist RL-06."""

from __future__ import annotations

from agent33.component_security.models import (
    FindingsSummary,
    SecurityGateDecision,
    SecurityGatePolicy,
    SecurityGateResult,
)


def evaluate_security_gate(
    *,
    run_id: str,
    summary: FindingsSummary,
    policy: SecurityGatePolicy,
) -> SecurityGateResult:
    """Evaluate findings summary against configured gate policy."""
    violations: list[str] = []
    if policy.block_on_critical and summary.critical > 0:
        violations.append(f"critical findings: {summary.critical}")
    if policy.block_on_high and summary.high > policy.max_high:
        violations.append(f"high findings: {summary.high} > allowed {policy.max_high}")
    if summary.medium > policy.max_medium:
        violations.append(f"medium findings: {summary.medium} > allowed {policy.max_medium}")

    if violations:
        return SecurityGateResult(
            decision=SecurityGateDecision.FAIL,
            message="Security gate failed - " + "; ".join(violations),
            run_id=run_id,
            summary=summary,
        )
    return SecurityGateResult(
        decision=SecurityGateDecision.PASS,
        message="Security gate passed",
        run_id=run_id,
        summary=summary,
    )
