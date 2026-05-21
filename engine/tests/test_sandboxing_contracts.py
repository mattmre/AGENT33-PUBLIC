from __future__ import annotations

from agent33.sandboxing.review import (
    SandboxReview,
    SandboxRisk,
    requires_review,
    sandbox_review_summary,
)


def test_sandbox_review_requires_review_for_risk_or_blockers() -> None:
    assert (
        requires_review(
            SandboxReview(
                surface="tool",
                risk=SandboxRisk.MEDIUM,
                recommendation="review filesystem access",
            )
        )
        is True
    )
    assert (
        requires_review(
            SandboxReview(
                surface="read-only",
                risk=SandboxRisk.LOW,
                recommendation="allow",
            )
        )
        is False
    )


def test_sandbox_review_summary_exposes_safe_mount_posture() -> None:
    summary = sandbox_review_summary(
        SandboxReview(
            surface="agent-os",
            risk=SandboxRisk.HIGH,
            recommendation="require contained workspace",
            blockers=["missing safe mount"],
        )
    )

    assert summary["requires_review"] is True
    assert summary["safe_mounts_required"] is True
    assert summary["blockers"] == ["missing safe mount"]
