from __future__ import annotations

from agent33.policy.capabilities import AuthorityLevel
from agent33.policy.collaboration import CollaborationMode, policy_for_mode


def test_review_only_mode_is_read_only() -> None:
    policy = policy_for_mode(CollaborationMode.REVIEW_ONLY)

    assert policy.authority == AuthorityLevel.READ_ONLY
    assert policy.requires_approval is False


def test_approval_required_mode_blocks_mutation_until_approval() -> None:
    policy = policy_for_mode(CollaborationMode.APPROVAL_REQUIRED)

    assert policy.authority == AuthorityLevel.DRY_RUN
    assert policy.requires_approval is True
    assert policy.completion_gate == "fail_closed"


def test_autonomous_mode_uses_fail_closed_completion() -> None:
    policy = policy_for_mode(CollaborationMode.AUTONOMOUS)

    assert policy.authority == AuthorityLevel.APPROVED_WRITE
    assert policy.completion_gate == "fail_closed"
