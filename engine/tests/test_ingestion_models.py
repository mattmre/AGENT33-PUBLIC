"""Tests for agent33.ingestion.models — CandidateAsset lifecycle type stub.

Verifies:
1. CandidateAsset can be constructed with all fields present.
2. status field validates against the CandidateStatus enum (rejects bad values).
3. confidence field validates against the ConfidenceLevel enum (rejects bad values).
4. revoked_at and revocation_reason default to None.
5. metadata defaults to an empty dict.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agent33.ingestion.models import (
    CandidateAsset,
    CandidateStatus,
    ConfidenceLevel,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def now() -> datetime:
    return datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)


@pytest.fixture()
def minimal_asset(now: datetime) -> CandidateAsset:
    """A CandidateAsset with only the required fields set."""
    return CandidateAsset(
        id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        name="my-test-skill",
        asset_type="skill",
        status=CandidateStatus.CANDIDATE,
        confidence=ConfidenceLevel.LOW,
        tenant_id="tenant-abc",
        created_at=now,
        updated_at=now,
    )


@pytest.fixture()
def full_asset(now: datetime) -> CandidateAsset:
    """A CandidateAsset with all optional fields explicitly populated."""
    later = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
    return CandidateAsset(
        id="11111111-2222-3333-4444-555555555555",
        name="community-pack",
        asset_type="pack",
        status=CandidateStatus.PUBLISHED,
        confidence=ConfidenceLevel.MEDIUM,
        source_uri="https://example.com/packs/community-pack",
        tenant_id="tenant-xyz",
        created_at=now,
        updated_at=later,
        validated_at=later,
        published_at=later,
        revoked_at=None,
        revocation_reason=None,
        metadata={"origin": "community-hub", "review_score": 4},
    )


# ---------------------------------------------------------------------------
# Test 1: CandidateAsset can be constructed with all fields
# ---------------------------------------------------------------------------


class TestCandidateAssetConstruction:
    def test_minimal_required_fields(self, minimal_asset: CandidateAsset) -> None:
        """Construction with only required fields must produce a valid model instance."""
        assert minimal_asset.id == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        assert minimal_asset.name == "my-test-skill"
        assert minimal_asset.asset_type == "skill"
        assert minimal_asset.tenant_id == "tenant-abc"

    def test_all_fields_populated(self, full_asset: CandidateAsset) -> None:
        """Construction with all optional fields must preserve every value."""
        assert full_asset.id == "11111111-2222-3333-4444-555555555555"
        assert full_asset.name == "community-pack"
        assert full_asset.asset_type == "pack"
        assert full_asset.source_uri == "https://example.com/packs/community-pack"
        assert full_asset.validated_at is not None
        assert full_asset.published_at is not None
        assert full_asset.metadata == {"origin": "community-hub", "review_score": 4}

    def test_extra_fields_are_rejected(self, now: datetime) -> None:
        """model_config extra='forbid' must reject unknown field names."""
        with pytest.raises(ValidationError) as exc_info:
            CandidateAsset(  # type: ignore[call-arg]
                id="x",
                name="x",
                asset_type="skill",
                status=CandidateStatus.CANDIDATE,
                confidence=ConfidenceLevel.LOW,
                tenant_id="t",
                created_at=now,
                updated_at=now,
                not_a_real_field="surprise",
            )
        errors = exc_info.value.errors()
        assert any(e["type"] == "extra_forbidden" for e in errors)


# ---------------------------------------------------------------------------
# Test 2: status field validates against CandidateStatus enum
# ---------------------------------------------------------------------------


class TestCandidateStatusValidation:
    @pytest.mark.parametrize(
        "status",
        [
            CandidateStatus.CANDIDATE,
            CandidateStatus.VALIDATED,
            CandidateStatus.PUBLISHED,
            CandidateStatus.REVOKED,
        ],
    )
    def test_valid_status_values_are_accepted(
        self, status: CandidateStatus, now: datetime
    ) -> None:
        """Every CandidateStatus enum member must be accepted by the model."""
        asset = CandidateAsset(
            id="x",
            name="x",
            asset_type="skill",
            status=status,
            confidence=ConfidenceLevel.LOW,
            tenant_id="t",
            created_at=now,
            updated_at=now,
        )
        assert asset.status == status

    def test_invalid_status_string_is_rejected(self, now: datetime) -> None:
        """A status value not in CandidateStatus must raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            CandidateAsset(
                id="x",
                name="x",
                asset_type="skill",
                status="pending",  # type: ignore[arg-type]
                confidence=ConfidenceLevel.LOW,
                tenant_id="t",
                created_at=now,
                updated_at=now,
            )
        errors = exc_info.value.errors()
        assert any("status" in str(e["loc"]) for e in errors)

    def test_status_enum_string_values(self) -> None:
        """CandidateStatus string values match the canonical lifecycle vocabulary."""
        assert CandidateStatus.CANDIDATE == "candidate"
        assert CandidateStatus.VALIDATED == "validated"
        assert CandidateStatus.PUBLISHED == "published"
        assert CandidateStatus.REVOKED == "revoked"


# ---------------------------------------------------------------------------
# Test 3: confidence field validates against ConfidenceLevel enum
# ---------------------------------------------------------------------------


class TestConfidenceLevelValidation:
    @pytest.mark.parametrize(
        "confidence",
        [
            ConfidenceLevel.HIGH,
            ConfidenceLevel.MEDIUM,
            ConfidenceLevel.LOW,
        ],
    )
    def test_valid_confidence_values_are_accepted(
        self, confidence: ConfidenceLevel, now: datetime
    ) -> None:
        """Every ConfidenceLevel enum member must be accepted by the model."""
        asset = CandidateAsset(
            id="x",
            name="x",
            asset_type="skill",
            status=CandidateStatus.CANDIDATE,
            confidence=confidence,
            tenant_id="t",
            created_at=now,
            updated_at=now,
        )
        assert asset.confidence == confidence

    def test_invalid_confidence_string_is_rejected(self, now: datetime) -> None:
        """A confidence value not in ConfidenceLevel must raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            CandidateAsset(
                id="x",
                name="x",
                asset_type="skill",
                status=CandidateStatus.CANDIDATE,
                confidence="trusted",  # type: ignore[arg-type]
                tenant_id="t",
                created_at=now,
                updated_at=now,
            )
        errors = exc_info.value.errors()
        assert any("confidence" in str(e["loc"]) for e in errors)

    def test_confidence_enum_string_values(self) -> None:
        """ConfidenceLevel string values match the trust vocabulary."""
        assert ConfidenceLevel.HIGH == "high"
        assert ConfidenceLevel.MEDIUM == "medium"
        assert ConfidenceLevel.LOW == "low"


# ---------------------------------------------------------------------------
# Test 4: revoked_at and revocation_reason default to None
# ---------------------------------------------------------------------------


class TestRevocationDefaults:
    def test_revoked_at_defaults_to_none(self, minimal_asset: CandidateAsset) -> None:
        """revoked_at must be None when not supplied at construction."""
        assert minimal_asset.revoked_at is None

    def test_revocation_reason_defaults_to_none(self, minimal_asset: CandidateAsset) -> None:
        """revocation_reason must be None when not supplied at construction."""
        assert minimal_asset.revocation_reason is None

    def test_revoked_asset_can_carry_timestamp_and_reason(self, now: datetime) -> None:
        """A REVOKED asset with explicit revoked_at and revocation_reason must store both."""
        revoked = CandidateAsset(
            id="x",
            name="x",
            asset_type="skill",
            status=CandidateStatus.REVOKED,
            confidence=ConfidenceLevel.LOW,
            tenant_id="t",
            created_at=now,
            updated_at=now,
            revoked_at=now,
            revocation_reason="CVE-2026-9999: upstream dependency vulnerability",
        )
        assert revoked.revoked_at == now
        assert revoked.revocation_reason == "CVE-2026-9999: upstream dependency vulnerability"

    def test_validated_at_and_published_at_default_to_none(
        self, minimal_asset: CandidateAsset
    ) -> None:
        """Optional timestamp fields default to None independently."""
        assert minimal_asset.validated_at is None
        assert minimal_asset.published_at is None


# ---------------------------------------------------------------------------
# Test 5: metadata defaults to empty dict
# ---------------------------------------------------------------------------


class TestMetadataDefault:
    def test_metadata_defaults_to_empty_dict(self, minimal_asset: CandidateAsset) -> None:
        """metadata must be an empty dict when not supplied at construction."""
        assert minimal_asset.metadata == {}

    def test_metadata_default_is_not_shared_across_instances(self, now: datetime) -> None:
        """default_factory=dict must produce independent dict objects per instance."""
        asset_a = CandidateAsset(
            id="a",
            name="a",
            asset_type="skill",
            status=CandidateStatus.CANDIDATE,
            confidence=ConfidenceLevel.LOW,
            tenant_id="t",
            created_at=now,
            updated_at=now,
        )
        asset_b = CandidateAsset(
            id="b",
            name="b",
            asset_type="skill",
            status=CandidateStatus.CANDIDATE,
            confidence=ConfidenceLevel.LOW,
            tenant_id="t",
            created_at=now,
            updated_at=now,
        )
        asset_a.metadata["key"] = "value"
        assert "key" not in asset_b.metadata

    def test_metadata_accepts_arbitrary_key_value_pairs(self, now: datetime) -> None:
        """metadata must accept heterogeneous key/value pairs."""
        asset = CandidateAsset(
            id="x",
            name="x",
            asset_type="tool",
            status=CandidateStatus.CANDIDATE,
            confidence=ConfidenceLevel.LOW,
            tenant_id="t",
            created_at=now,
            updated_at=now,
            metadata={"score": 0.9, "tags": ["trusted", "verified"], "source": "hub"},
        )
        assert asset.metadata["score"] == 0.9
        assert asset.metadata["tags"] == ["trusted", "verified"]
        assert asset.metadata["source"] == "hub"
