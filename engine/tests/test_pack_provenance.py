"""Tests for pack provenance signing/verification and version conflict detection.

Tests cover: HMAC-SHA256 sign + verify round-trip, tampered manifest detection,
trust policy evaluation, version conflict detection, and conflict resolution.
"""

from __future__ import annotations

import pytest

from agent33.packs.conflicts import (
    ConflictKind,
    ResolutionAction,
    detect_conflicts,
    resolve_conflicts,
)
from agent33.packs.manifest import PackManifest
from agent33.packs.models import PackSkillEntry
from agent33.packs.provenance import (
    PackProvenance,
    PackTrustPolicy,
    TrustLevel,
    evaluate_trust,
    sign_pack,
    verify_pack,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_manifest(
    name: str = "test-pack",
    version: str = "1.0.0",
    *,
    skills: list[str] | None = None,
    deps: list[tuple[str, str]] | None = None,
) -> PackManifest:
    """Create a minimal PackManifest for testing."""
    from agent33.packs.manifest import PackDependencies
    from agent33.packs.models import PackDependency

    skill_entries = [
        PackSkillEntry(name=s, path=f"skills/{s}") for s in (skills or ["default-skill"])
    ]
    pack_deps = [PackDependency(name=n, version_constraint=c) for n, c in (deps or [])]
    return PackManifest(
        name=name,
        version=version,
        description=f"Test pack {name}",
        author="tester",
        skills=skill_entries,
        dependencies=PackDependencies(packs=pack_deps),
    )


# ---------------------------------------------------------------------------
# Signing & Verification
# ---------------------------------------------------------------------------


class TestPackSigning:
    """Test HMAC-SHA256 sign + verify round-trip."""

    def test_sign_returns_provenance(self) -> None:
        manifest = _make_manifest()
        prov = sign_pack(manifest, "secret-key", signer_id="ci-bot")

        assert isinstance(prov, PackProvenance)
        assert prov.signer_id == "ci-bot"
        assert prov.algorithm == "sha256"
        assert len(prov.signature) == 64  # SHA-256 hex digest length
        assert prov.trust_level == TrustLevel.COMMUNITY

    def test_sign_with_custom_trust_level(self) -> None:
        manifest = _make_manifest()
        prov = sign_pack(
            manifest,
            "key",
            signer_id="org",
            trust_level=TrustLevel.OFFICIAL,
        )
        assert prov.trust_level == TrustLevel.OFFICIAL

    def test_verify_valid_signature(self) -> None:
        """Sign + verify round-trip should succeed."""
        manifest = _make_manifest()
        key = "my-secret-key"
        prov = sign_pack(manifest, key, signer_id="signer-1")

        assert verify_pack(manifest, prov, key) is True

    def test_verify_wrong_key_fails(self) -> None:
        """Verification with wrong key should fail."""
        manifest = _make_manifest()
        prov = sign_pack(manifest, "correct-key", signer_id="s")

        assert verify_pack(manifest, prov, "wrong-key") is False

    def test_verify_tampered_manifest_fails(self) -> None:
        """Modifying the manifest after signing should fail verification."""
        manifest = _make_manifest(name="original", version="1.0.0")
        key = "the-key"
        prov = sign_pack(manifest, key, signer_id="s")

        # Tamper: create a manifest with different version
        tampered = _make_manifest(name="original", version="1.0.1")

        assert verify_pack(tampered, prov, key) is False

    def test_verify_tampered_description_fails(self) -> None:
        """Even subtle changes (description) should break signature."""
        manifest = _make_manifest()
        key = "k"
        prov = sign_pack(manifest, key, signer_id="s")

        tampered = manifest.model_copy(update={"description": "different desc"})
        assert verify_pack(tampered, prov, key) is False

    def test_verify_unsupported_algorithm(self) -> None:
        """Provenance with unsupported algorithm should fail verification."""
        manifest = _make_manifest()
        prov = PackProvenance(
            signer_id="s",
            signature="abc123",
            algorithm="md5",
        )
        assert verify_pack(manifest, prov, "key") is False

    def test_deterministic_signing(self) -> None:
        """Same manifest + key should produce the same signature."""
        manifest = _make_manifest()
        key = "deterministic-key"
        sig1 = sign_pack(manifest, key, signer_id="s").signature
        sig2 = sign_pack(manifest, key, signer_id="s").signature
        assert sig1 == sig2


# ---------------------------------------------------------------------------
# Trust Policy Evaluation
# ---------------------------------------------------------------------------


class TestTrustPolicy:
    """Test trust policy evaluation logic."""

    def test_no_provenance_no_requirement(self) -> None:
        """No provenance + no signature required → allowed."""
        policy = PackTrustPolicy(require_signature=False)
        decision = evaluate_trust(None, policy)
        assert decision.allowed is True

    def test_no_provenance_signature_required(self) -> None:
        """No provenance + signature required → rejected."""
        policy = PackTrustPolicy(require_signature=True)
        decision = evaluate_trust(None, policy)
        assert decision.allowed is False
        assert "requires a signature" in decision.reason

    def test_provenance_meets_policy(self) -> None:
        """Provenance with sufficient trust level → allowed."""
        prov = PackProvenance(
            signer_id="trusted-org",
            signature="abcd1234" * 8,
            trust_level=TrustLevel.VERIFIED,
        )
        policy = PackTrustPolicy(
            require_signature=True,
            min_trust_level=TrustLevel.COMMUNITY,
        )
        decision = evaluate_trust(prov, policy)
        assert decision.allowed is True

    def test_trust_level_too_low(self) -> None:
        """Provenance trust below policy minimum → rejected."""
        prov = PackProvenance(
            signer_id="random",
            signature="abcd1234" * 8,
            trust_level=TrustLevel.COMMUNITY,
        )
        policy = PackTrustPolicy(
            require_signature=True,
            min_trust_level=TrustLevel.OFFICIAL,
        )
        decision = evaluate_trust(prov, policy)
        assert decision.allowed is False
        assert "below" in decision.reason

    def test_signer_not_in_allowlist(self) -> None:
        """Signer not in allowed_signers list → rejected."""
        prov = PackProvenance(
            signer_id="outsider",
            signature="abcd1234" * 8,
            trust_level=TrustLevel.OFFICIAL,
        )
        policy = PackTrustPolicy(
            require_signature=True,
            allowed_signers=["internal-ci", "release-bot"],
        )
        decision = evaluate_trust(prov, policy)
        assert decision.allowed is False
        assert "not in the allowed signers" in decision.reason

    def test_signer_in_allowlist(self) -> None:
        """Signer in allowed_signers list → allowed."""
        prov = PackProvenance(
            signer_id="internal-ci",
            signature="abcd1234" * 8,
            trust_level=TrustLevel.VERIFIED,
        )
        policy = PackTrustPolicy(
            require_signature=True,
            allowed_signers=["internal-ci", "release-bot"],
            min_trust_level=TrustLevel.COMMUNITY,
        )
        decision = evaluate_trust(prov, policy)
        assert decision.allowed is True

    def test_empty_allowlist_allows_any_signer(self) -> None:
        """Empty allowed_signers list means any signer is accepted."""
        prov = PackProvenance(
            signer_id="anyone",
            signature="abcd1234" * 8,
            trust_level=TrustLevel.COMMUNITY,
        )
        policy = PackTrustPolicy(
            require_signature=True,
            allowed_signers=[],
            min_trust_level=TrustLevel.UNTRUSTED,
        )
        decision = evaluate_trust(prov, policy)
        assert decision.allowed is True

    def test_trust_level_ordering(self) -> None:
        """Verify trust level ordering: untrusted < community < verified < official."""
        for lower, higher in [
            (TrustLevel.UNTRUSTED, TrustLevel.COMMUNITY),
            (TrustLevel.COMMUNITY, TrustLevel.VERIFIED),
            (TrustLevel.VERIFIED, TrustLevel.OFFICIAL),
        ]:
            prov = PackProvenance(
                signer_id="s",
                signature="abcd1234" * 8,
                trust_level=lower,
            )
            policy = PackTrustPolicy(min_trust_level=higher)
            decision = evaluate_trust(prov, policy)
            assert decision.allowed is False, f"{lower} should be below {higher}"


# ---------------------------------------------------------------------------
# Version Conflict Detection
# ---------------------------------------------------------------------------


class TestConflictDetection:
    """Test conflict detection between packs."""

    def test_no_conflicts(self) -> None:
        """Packs with no overlapping skills or deps have no conflicts."""
        a = _make_manifest("pack-a", skills=["skill-1"])
        b = _make_manifest("pack-b", skills=["skill-2"])
        conflicts = detect_conflicts(a, b)
        assert conflicts == []

    def test_skill_name_overlap(self) -> None:
        """Packs with overlapping skill names produce a conflict."""
        a = _make_manifest("pack-a", skills=["shared-skill", "unique-a"])
        b = _make_manifest("pack-b", skills=["shared-skill", "unique-b"])
        conflicts = detect_conflicts(a, b)

        assert len(conflicts) == 1
        assert conflicts[0].kind == ConflictKind.SKILL_NAME_OVERLAP
        assert conflicts[0].skill_name == "shared-skill"
        assert "pack-a" in conflicts[0].detail
        assert "pack-b" in conflicts[0].detail

    def test_multiple_skill_overlaps(self) -> None:
        """Multiple overlapping skills produce multiple conflicts."""
        a = _make_manifest("pack-a", skills=["s1", "s2", "s3"])
        b = _make_manifest("pack-b", skills=["s2", "s3", "s4"])
        conflicts = detect_conflicts(a, b)
        assert len(conflicts) == 2
        names = {c.skill_name for c in conflicts}
        assert names == {"s2", "s3"}

    def test_compatible_shared_dependency(self) -> None:
        """Shared deps with overlapping constraints → no conflict."""
        a = _make_manifest("pack-a", deps=[("utils", "^1.0.0")])
        b = _make_manifest("pack-b", deps=[("utils", "^1.2.0")])
        conflicts = detect_conflicts(a, b)

        # ^1.0.0 and ^1.2.0 overlap (e.g. 1.2.0 satisfies both)
        dep_conflicts = [c for c in conflicts if c.kind == ConflictKind.VERSION_RANGE_INCOMPATIBLE]
        assert len(dep_conflicts) == 0

    def test_incompatible_shared_dependency(self) -> None:
        """Shared deps with non-overlapping constraints → conflict."""
        a = _make_manifest("pack-a", deps=[("utils", "^1.0.0")])
        b = _make_manifest("pack-b", deps=[("utils", "^2.0.0")])
        conflicts = detect_conflicts(a, b)

        dep_conflicts = [c for c in conflicts if c.kind == ConflictKind.VERSION_RANGE_INCOMPATIBLE]
        assert len(dep_conflicts) == 1
        assert "utils" in dep_conflicts[0].detail

    def test_no_shared_dependencies_no_conflict(self) -> None:
        """Packs with disjoint dependency sets have no dep conflicts."""
        a = _make_manifest("pack-a", skills=["skill-a"], deps=[("lib-a", "^1.0.0")])
        b = _make_manifest("pack-b", skills=["skill-b"], deps=[("lib-b", "^1.0.0")])
        conflicts = detect_conflicts(a, b)
        assert conflicts == []


# ---------------------------------------------------------------------------
# Conflict Resolution
# ---------------------------------------------------------------------------


class TestConflictResolution:
    """Test conflict resolution strategies."""

    def _sample_conflicts(self) -> list:
        a = _make_manifest("pack-a", skills=["shared"])
        b = _make_manifest("pack-b", skills=["shared"])
        return detect_conflicts(a, b)

    def test_reject_strategy(self) -> None:
        conflicts = self._sample_conflicts()
        resolutions = resolve_conflicts(conflicts, strategy="reject")
        assert len(resolutions) == 1
        assert resolutions[0].action == ResolutionAction.REJECT

    def test_manual_strategy(self) -> None:
        conflicts = self._sample_conflicts()
        resolutions = resolve_conflicts(conflicts, strategy="manual")
        assert len(resolutions) == 1
        assert resolutions[0].action == ResolutionAction.MANUAL

    def test_latest_strategy_prefers_higher_version(self) -> None:
        conflicts = self._sample_conflicts()
        resolutions = resolve_conflicts(
            conflicts,
            strategy="latest",
            versions={"pack-a": "1.0.0", "pack-b": "2.0.0"},
        )
        assert len(resolutions) == 1
        assert resolutions[0].action == ResolutionAction.USE_B
        assert resolutions[0].chosen_pack == "pack-b"

    def test_latest_strategy_equal_versions_prefers_a(self) -> None:
        conflicts = self._sample_conflicts()
        resolutions = resolve_conflicts(
            conflicts,
            strategy="latest",
            versions={"pack-a": "1.0.0", "pack-b": "1.0.0"},
        )
        assert len(resolutions) == 1
        assert resolutions[0].action == ResolutionAction.USE_A

    def test_latest_strategy_missing_version_falls_back_to_manual(self) -> None:
        conflicts = self._sample_conflicts()
        resolutions = resolve_conflicts(
            conflicts,
            strategy="latest",
            versions={"pack-a": "1.0.0"},  # missing pack-b
        )
        assert resolutions[0].action == ResolutionAction.MANUAL

    def test_unknown_strategy_raises(self) -> None:
        conflicts = self._sample_conflicts()
        with pytest.raises(ValueError, match="Unknown conflict resolution strategy"):
            resolve_conflicts(conflicts, strategy="yolo")

    def test_empty_conflicts_list(self) -> None:
        resolutions = resolve_conflicts([], strategy="reject")
        assert resolutions == []
