"""Tests for persisted pack trust policy management."""

from __future__ import annotations

from agent33.packs.provenance import TrustLevel
from agent33.packs.trust_manager import TrustPolicyManager
from agent33.services.orchestration_state import OrchestrationStateStore


def test_trust_manager_persists_updates(tmp_path) -> None:
    state_store = OrchestrationStateStore(str(tmp_path / "trust.json"))
    manager = TrustPolicyManager(state_store)

    manager.update_policy(
        require_signature=True,
        min_trust_level=TrustLevel.VERIFIED,
        allowed_signers=["ops-team"],
    )

    reloaded = TrustPolicyManager(state_store)
    policy = reloaded.get_policy()
    assert policy.require_signature is True
    assert policy.min_trust_level == TrustLevel.VERIFIED
    assert policy.allowed_signers == ["ops-team"]
