"""Unit tests for the ingestion service and state machine (Sprint 1).

Tests assert on real transition outcomes, error types, DB round-trips, and
restart hydration.  Every assertion is tied to a specific behaviour that would
catch a real regression.

Test plan:
  TC-S1  ingest() creates a CANDIDATE with LOW confidence by default
  TC-S2  validate() moves CANDIDATE → VALIDATED
  TC-S3  promote() moves VALIDATED → PUBLISHED
  TC-S4  revoke() moves PUBLISHED → REVOKED and stores the reason
  TC-S5  Invalid transition raises CandidateTransitionError (type asserted)
  TC-S6  REVOKED is terminal — no further transitions permitted
  TC-S7  Persistence write-through on ingest, validate, promote, revoke
  TC-S8  Restart hydration: service2 can get() an asset ingested by service1
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agent33.ingestion.models import CandidateAsset, CandidateStatus, ConfidenceLevel
from agent33.ingestion.persistence import IngestionPersistence
from agent33.ingestion.service import IngestionService
from agent33.ingestion.state_machine import CandidateStateMachine, CandidateTransitionError
from agent33.skills.registry import SkillRegistry

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_TENANT = "tenant-ingestion-test"


def _ingest(svc: IngestionService, *, name: str = "test-asset") -> CandidateAsset:
    return svc.ingest(
        name=name,
        asset_type="skill",
        source_uri="https://example.com/skill.yaml",
        tenant_id=_TENANT,
    )


@pytest.fixture()
def svc() -> IngestionService:
    """In-memory service (no persistence)."""
    return IngestionService()


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_ingestion.db"


@pytest.fixture()
def svc_with_db(db_path: Path) -> IngestionService:
    p = IngestionPersistence(db_path)
    s = IngestionService(persistence=p)
    yield s
    p.close()


# ---------------------------------------------------------------------------
# TC-S1: ingest() creates CANDIDATE with LOW confidence
# ---------------------------------------------------------------------------


class TestIngest:
    """TC-S1: ingest() creates the record in CANDIDATE/LOW status."""

    def test_ingest_status_is_candidate(self, svc: IngestionService) -> None:
        asset = _ingest(svc)
        assert asset.status == CandidateStatus.CANDIDATE

    def test_ingest_default_confidence_is_low(self, svc: IngestionService) -> None:
        asset = _ingest(svc)
        assert asset.confidence == ConfidenceLevel.LOW

    def test_ingest_custom_confidence(self, svc: IngestionService) -> None:
        asset = svc.ingest(
            name="hi-conf",
            asset_type="tool",
            source_uri=None,
            tenant_id=_TENANT,
            confidence=ConfidenceLevel.HIGH,
        )
        assert asset.confidence == ConfidenceLevel.HIGH

    def test_ingest_caller_cannot_set_non_candidate_status(self, svc: IngestionService) -> None:
        """ingest() must always create CANDIDATE — the caller has no override."""
        # The only way to create an asset is via ingest(); validate() must be
        # called explicitly.  Verify the status is always CANDIDATE on creation.
        asset = svc.ingest(
            name="force-status",
            asset_type="pack",
            source_uri=None,
            tenant_id=_TENANT,
        )
        assert asset.status == CandidateStatus.CANDIDATE

    def test_ingest_asset_is_retrievable(self, svc: IngestionService) -> None:
        asset = _ingest(svc)
        retrieved = svc.get(asset.id)
        assert retrieved is not None
        assert retrieved.id == asset.id

    def test_ingest_metadata_stored(self, svc: IngestionService) -> None:
        asset = svc.ingest(
            name="meta-asset",
            asset_type="workflow",
            source_uri=None,
            tenant_id=_TENANT,
            metadata={"version": "1.2.3", "tags": ["beta"]},
        )
        assert asset.metadata == {"version": "1.2.3", "tags": ["beta"]}


# ---------------------------------------------------------------------------
# TC-S2: validate() moves CANDIDATE → VALIDATED
# ---------------------------------------------------------------------------


class TestValidate:
    """TC-S2: validate() transitions CANDIDATE → VALIDATED."""

    def test_validate_changes_status_to_validated(self, svc: IngestionService) -> None:
        asset = _ingest(svc)
        updated = svc.validate(asset.id)
        assert updated.status == CandidateStatus.VALIDATED

    def test_validate_sets_validated_at_timestamp(self, svc: IngestionService) -> None:
        asset = _ingest(svc)
        updated = svc.validate(asset.id)
        assert updated.validated_at is not None

    def test_validate_does_not_affect_other_fields(self, svc: IngestionService) -> None:
        asset = _ingest(svc, name="stable-name")
        updated = svc.validate(asset.id)
        assert updated.name == "stable-name"
        assert updated.tenant_id == _TENANT


# ---------------------------------------------------------------------------
# TC-S3: promote() moves VALIDATED → PUBLISHED
# ---------------------------------------------------------------------------


class TestPromote:
    """TC-S3: promote() transitions VALIDATED → PUBLISHED."""

    def test_promote_changes_status_to_published(self, svc: IngestionService) -> None:
        asset = _ingest(svc)
        svc.validate(asset.id)
        updated = svc.promote(asset.id)
        assert updated.status == CandidateStatus.PUBLISHED

    def test_promote_sets_published_at_timestamp(self, svc: IngestionService) -> None:
        asset = _ingest(svc)
        svc.validate(asset.id)
        updated = svc.promote(asset.id)
        assert updated.published_at is not None

    def test_promote_from_candidate_raises_transition_error(self, svc: IngestionService) -> None:
        """Cannot jump from CANDIDATE directly to PUBLISHED."""
        asset = _ingest(svc)
        with pytest.raises(CandidateTransitionError):
            svc.promote(asset.id)

    def test_promote_registers_skill_assets_into_registry(self) -> None:
        registry = SkillRegistry()
        service = IngestionService(skill_registry=registry)
        asset = service.ingest(
            name="runtime-skill",
            asset_type="skill",
            source_uri=None,
            tenant_id=_TENANT,
            metadata={
                "skill_definition": {
                    "name": "runtime-skill",
                    "description": "Promoted skill",
                    "instructions": "Use the promoted runtime skill.",
                    "allowed_tools": ["shell"],
                }
            },
        )

        service.validate(asset.id)
        service.promote(asset.id)

        registered = registry.get("runtime-skill")
        assert registered is not None
        assert registered.description == "Promoted skill"
        assert registered.allowed_tools == ["shell"]

    def test_promote_skips_malformed_skill_assets_without_failing(self) -> None:
        registry = SkillRegistry()
        service = IngestionService(skill_registry=registry)
        asset = service.ingest(
            name="broken-skill",
            asset_type="skill",
            source_uri=None,
            tenant_id=_TENANT,
            metadata={"skill_definition": "not-a-mapping"},
        )

        service.validate(asset.id)
        promoted = service.promote(asset.id)

        assert promoted.status == CandidateStatus.PUBLISHED
        assert registry.count == 0

    def test_promote_skips_non_skill_assets_even_with_skill_metadata(self) -> None:
        registry = SkillRegistry()
        service = IngestionService(skill_registry=registry)
        asset = service.ingest(
            name="workflow-asset",
            asset_type="workflow",
            source_uri=None,
            tenant_id=_TENANT,
            metadata={
                "skill_definition": {
                    "name": "workflow-asset",
                    "description": "Should not register.",
                }
            },
        )

        service.validate(asset.id)
        service.promote(asset.id)

        assert registry.count == 0


# ---------------------------------------------------------------------------
# TC-S4: revoke() stores reason and sets correct status
# ---------------------------------------------------------------------------


class TestRevoke:
    """TC-S4: revoke() transitions to REVOKED with reason."""

    def test_revoke_published_asset(self, svc: IngestionService) -> None:
        asset = _ingest(svc)
        svc.validate(asset.id)
        svc.promote(asset.id)
        updated = svc.revoke(asset.id, reason="Security issue discovered")
        assert updated.status == CandidateStatus.REVOKED

    def test_revoke_stores_reason(self, svc: IngestionService) -> None:
        asset = _ingest(svc)
        svc.validate(asset.id)
        svc.promote(asset.id)
        updated = svc.revoke(asset.id, reason="Licence ambiguity")
        assert updated.revocation_reason == "Licence ambiguity"

    def test_revoke_sets_revoked_at_timestamp(self, svc: IngestionService) -> None:
        asset = _ingest(svc)
        svc.validate(asset.id)
        svc.promote(asset.id)
        updated = svc.revoke(asset.id, reason="Test revocation")
        assert updated.revoked_at is not None

    def test_revoke_candidate_directly(self, svc: IngestionService) -> None:
        """CANDIDATE → REVOKED is a valid transition (reject without review)."""
        asset = _ingest(svc)
        updated = svc.revoke(asset.id, reason="Rejected at intake")
        assert updated.status == CandidateStatus.REVOKED

    def test_revoke_validated_asset(self, svc: IngestionService) -> None:
        """VALIDATED → REVOKED is a valid transition (fail validation)."""
        asset = _ingest(svc)
        svc.validate(asset.id)
        updated = svc.revoke(asset.id, reason="Failed validation check")
        assert updated.status == CandidateStatus.REVOKED


# ---------------------------------------------------------------------------
# TC-S5: Invalid transitions raise CandidateTransitionError (type asserted)
# ---------------------------------------------------------------------------


class TestInvalidTransitions:
    """TC-S5: Invalid transitions raise CandidateTransitionError."""

    def test_candidate_to_published_raises_error(self, svc: IngestionService) -> None:
        asset = _ingest(svc)
        with pytest.raises(CandidateTransitionError) as exc_info:
            svc.promote(asset.id)
        assert exc_info.type is CandidateTransitionError

    def test_validated_to_candidate_raises_error(self, svc: IngestionService) -> None:
        """Cannot go backwards in the lifecycle."""
        asset = _ingest(svc)
        svc.validate(asset.id)
        # There is no method to go back to CANDIDATE — exercise via state machine directly
        from agent33.ingestion.state_machine import CandidateStateMachine

        sm = CandidateStateMachine()
        validated_asset = svc.get(asset.id)
        assert validated_asset is not None
        with pytest.raises(CandidateTransitionError) as exc_info:
            sm.transition(validated_asset, CandidateStatus.CANDIDATE)
        assert exc_info.type is CandidateTransitionError

    def test_error_message_contains_both_statuses(self, svc: IngestionService) -> None:
        asset = _ingest(svc)
        with pytest.raises(CandidateTransitionError) as exc_info:
            svc.promote(asset.id)
        message = str(exc_info.value)
        assert "candidate" in message
        assert "published" in message


# ---------------------------------------------------------------------------
# TC-S6: REVOKED is a terminal state
# ---------------------------------------------------------------------------


class TestRevokedTerminal:
    """TC-S6: REVOKED is terminal — no further transitions permitted."""

    def test_cannot_validate_revoked_asset(self, svc: IngestionService) -> None:
        asset = _ingest(svc)
        svc.revoke(asset.id, reason="Rejected")
        with pytest.raises(CandidateTransitionError) as exc_info:
            svc.validate(asset.id)
        assert exc_info.type is CandidateTransitionError

    def test_cannot_promote_revoked_asset(self, svc: IngestionService) -> None:
        asset = _ingest(svc)
        svc.revoke(asset.id, reason="Rejected")
        with pytest.raises(CandidateTransitionError) as exc_info:
            svc.promote(asset.id)
        assert exc_info.type is CandidateTransitionError

    def test_cannot_re_revoke_revoked_asset(self, svc: IngestionService) -> None:
        asset = _ingest(svc)
        svc.revoke(asset.id, reason="First revocation")
        with pytest.raises(CandidateTransitionError) as exc_info:
            svc.revoke(asset.id, reason="Second revocation attempt")
        assert exc_info.type is CandidateTransitionError

    def test_valid_transitions_map_has_empty_set_for_revoked(self) -> None:
        """The VALID_TRANSITIONS constant must declare REVOKED as terminal."""
        sm = CandidateStateMachine()
        assert sm.VALID_TRANSITIONS[CandidateStatus.REVOKED] == set()


# ---------------------------------------------------------------------------
# TC-S7: Persistence write-through
# ---------------------------------------------------------------------------


class TestPersistenceWriteThrough:
    """TC-S7: ingest, validate, promote, and revoke write through to the DB."""

    def test_ingest_writes_to_db(self, svc_with_db: IngestionService) -> None:
        asset = _ingest(svc_with_db)
        assert svc_with_db._persistence is not None
        loaded = svc_with_db._persistence.load(asset.id)
        assert loaded is not None
        assert loaded.id == asset.id
        assert loaded.status == CandidateStatus.CANDIDATE

    def test_validate_writes_to_db(self, svc_with_db: IngestionService) -> None:
        asset = _ingest(svc_with_db)
        svc_with_db.validate(asset.id)
        assert svc_with_db._persistence is not None
        loaded = svc_with_db._persistence.load(asset.id)
        assert loaded is not None
        assert loaded.status == CandidateStatus.VALIDATED
        assert loaded.validated_at is not None

    def test_promote_writes_to_db(self, svc_with_db: IngestionService) -> None:
        asset = _ingest(svc_with_db)
        svc_with_db.validate(asset.id)
        svc_with_db.promote(asset.id)
        assert svc_with_db._persistence is not None
        loaded = svc_with_db._persistence.load(asset.id)
        assert loaded is not None
        assert loaded.status == CandidateStatus.PUBLISHED
        assert loaded.published_at is not None

    def test_revoke_writes_to_db(self, svc_with_db: IngestionService) -> None:
        asset = _ingest(svc_with_db)
        svc_with_db.validate(asset.id)
        svc_with_db.promote(asset.id)
        svc_with_db.revoke(asset.id, reason="Post-publish retract")
        assert svc_with_db._persistence is not None
        loaded = svc_with_db._persistence.load(asset.id)
        assert loaded is not None
        assert loaded.status == CandidateStatus.REVOKED
        assert loaded.revocation_reason == "Post-publish retract"
        assert loaded.revoked_at is not None


# ---------------------------------------------------------------------------
# TC-S8: Restart hydration
# ---------------------------------------------------------------------------


class TestRestartHydration:
    """TC-S8: service2 re-hydrates from the same DB as service1."""

    def test_ingested_asset_survives_restart(self, db_path: Path) -> None:
        """An asset ingested by service1 must be retrievable by service2."""
        p1 = IngestionPersistence(db_path)
        svc1 = IngestionService(persistence=p1)
        asset = _ingest(svc1)
        asset_id = asset.id
        p1.close()

        # Simulate restart
        p2 = IngestionPersistence(db_path)
        svc2 = IngestionService(persistence=p2)
        retrieved = svc2.get(asset_id)
        assert retrieved is not None
        assert retrieved.id == asset_id
        assert retrieved.name == "test-asset"
        assert retrieved.status == CandidateStatus.CANDIDATE
        p2.close()

    def test_full_lifecycle_survives_restart(self, db_path: Path) -> None:
        """A PUBLISHED asset ingested by service1 is PUBLISHED in service2."""
        p1 = IngestionPersistence(db_path)
        svc1 = IngestionService(persistence=p1)
        asset = _ingest(svc1)
        svc1.validate(asset.id)
        svc1.promote(asset.id)
        asset_id = asset.id
        p1.close()

        p2 = IngestionPersistence(db_path)
        svc2 = IngestionService(persistence=p2)
        retrieved = svc2.get(asset_id)
        assert retrieved is not None
        assert retrieved.status == CandidateStatus.PUBLISHED
        assert retrieved.published_at is not None
        p2.close()

    def test_published_skill_rehydrates_into_registry_on_restart(self, db_path: Path) -> None:
        """Published skill assets should repopulate the runtime registry after restart."""
        p1 = IngestionPersistence(db_path)
        registry1 = SkillRegistry()
        svc1 = IngestionService(persistence=p1, skill_registry=registry1)
        asset = svc1.ingest(
            name="rehydrated-skill",
            asset_type="skill",
            source_uri=None,
            tenant_id=_TENANT,
            metadata={
                "skill_definition": {
                    "name": "rehydrated-skill",
                    "description": "Survives restart.",
                    "instructions": "Hydrated from persistence.",
                }
            },
        )
        svc1.validate(asset.id)
        svc1.promote(asset.id)
        p1.close()

        p2 = IngestionPersistence(db_path)
        registry2 = SkillRegistry()
        svc2 = IngestionService(persistence=p2, skill_registry=registry2)

        assert svc2.get(asset.id) is not None
        registered = registry2.get("rehydrated-skill")
        assert registered is not None
        assert registered.description == "Survives restart."
        p2.close()

    def test_list_by_status_works_after_restart(self, db_path: Path) -> None:
        """list_by_status() in service2 reflects assets written by service1."""
        p1 = IngestionPersistence(db_path)
        svc1 = IngestionService(persistence=p1)
        a1 = _ingest(svc1, name="asset-a")
        a2 = _ingest(svc1, name="asset-b")
        svc1.validate(a1.id)
        p1.close()

        p2 = IngestionPersistence(db_path)
        svc2 = IngestionService(persistence=p2)
        candidates = svc2.list_by_status(CandidateStatus.CANDIDATE)
        validated = svc2.list_by_status(CandidateStatus.VALIDATED)
        assert any(a.id == a2.id for a in candidates)
        assert any(a.id == a1.id for a in validated)
        p2.close()
