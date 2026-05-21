"""Tests for marketplace curation: state machine, quality, service, categories, and API.

Covers:
  - CurationStateMachine: valid transitions, invalid transitions, valid_next_states
  - assess_pack_quality: high/low/partial quality packs
  - CurationService: submit, review approve+list, changes_requested, feature/unfeature,
    verify, deprecate, unlist
  - CategoryRegistry: default seeding, add, update, remove, duplicate slug
  - API routes: submit, get curation, list curated, review, feature, verify,
    deprecate, quality assessment, categories CRUD, featured listing
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from agent33.packs.categories import CategoryRegistry, MarketplaceCategory
from agent33.packs.curation import (
    CurationStateMachine,
    CurationStatus,
    InvalidCurationTransitionError,
    QualityAssessment,
    assess_pack_quality,
    build_curation_review_signals,
)
from agent33.packs.curation_service import CurationService
from agent33.packs.manifest import PackManifest  # noqa: TC001
from agent33.packs.models import PackSkillEntry
from agent33.packs.provenance_models import PackProvenance  # noqa: TC001

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_manifest(
    *,
    name: str = "test-pack",
    version: str = "1.0.0",
    description: str = "A high-quality test pack with a thorough description",
    author: str = "tester",
    license_: str = "MIT",
    tags: list[str] | None = None,
    category: str = "testing",
    skills: list[PackSkillEntry] | None = None,
) -> PackManifest:
    """Build a PackManifest for testing."""
    return PackManifest(
        name=name,
        version=version,
        description=description,
        author=author,
        license=license_,
        tags=tags if tags is not None else ["testing", "automation"],
        category=category,
        skills=skills or [PackSkillEntry(name="skill-1", path="skills/skill-1")],
    )


def _make_provenance() -> PackProvenance:
    return PackProvenance(signer_id="ci-bot", signature="abcdef1234567890")


class _FakeInstalledPack:
    """Minimal installed-pack stand-in for CurationService tests."""

    def __init__(
        self,
        *,
        name: str = "test-pack",
        version: str = "1.0.0",
        description: str = "A high-quality test pack with a thorough description",
        author: str = "tester",
        pack_license: str = "MIT",
        tags: list[str] | None = None,
        category: str = "testing",
        provenance: PackProvenance | None = None,
    ) -> None:
        self.name = name
        self.version = version
        self.description = description
        self.author = author
        self.license = pack_license
        self.tags = tags if tags is not None else ["testing", "automation"]
        self.category = category
        self.provenance = provenance
        self.skills = [
            PackSkillEntry(name="skill-1", path="skills/skill-1"),
        ]


class _FakePackRegistry:
    """Minimal pack registry stand-in for CurationService tests."""

    def __init__(self, packs: dict[str, _FakeInstalledPack] | None = None) -> None:
        self._packs = packs or {}

    def get(self, name: str) -> _FakeInstalledPack | None:
        return self._packs.get(name)

    def add(self, pack: _FakeInstalledPack) -> None:
        self._packs[pack.name] = pack


class _FakeStateStore:
    """In-memory state store for persistence tests."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def read_namespace(self, namespace: str) -> dict[str, Any]:
        return self._data.get(namespace, {})

    def write_namespace(self, namespace: str, payload: dict[str, Any]) -> None:
        self._data[namespace] = payload


# ============================================================================
# CurationStateMachine tests
# ============================================================================


class TestCurationStateMachine:
    """Test valid/invalid transitions and valid_next_states."""

    def test_valid_transition_draft_to_submitted(self) -> None:
        assert CurationStateMachine.can_transition(CurationStatus.DRAFT, CurationStatus.SUBMITTED)
        result = CurationStateMachine.transition(CurationStatus.DRAFT, CurationStatus.SUBMITTED)
        assert result == CurationStatus.SUBMITTED

    def test_valid_transition_submitted_to_under_review(self) -> None:
        result = CurationStateMachine.transition(
            CurationStatus.SUBMITTED, CurationStatus.UNDER_REVIEW
        )
        assert result == CurationStatus.UNDER_REVIEW

    def test_valid_transition_under_review_to_approved(self) -> None:
        result = CurationStateMachine.transition(
            CurationStatus.UNDER_REVIEW, CurationStatus.APPROVED
        )
        assert result == CurationStatus.APPROVED

    def test_valid_transition_under_review_to_changes_requested(self) -> None:
        result = CurationStateMachine.transition(
            CurationStatus.UNDER_REVIEW, CurationStatus.CHANGES_REQUESTED
        )
        assert result == CurationStatus.CHANGES_REQUESTED

    def test_valid_transition_changes_requested_to_submitted(self) -> None:
        result = CurationStateMachine.transition(
            CurationStatus.CHANGES_REQUESTED, CurationStatus.SUBMITTED
        )
        assert result == CurationStatus.SUBMITTED

    def test_valid_transition_approved_to_listed(self) -> None:
        result = CurationStateMachine.transition(CurationStatus.APPROVED, CurationStatus.LISTED)
        assert result == CurationStatus.LISTED

    def test_valid_transition_listed_to_featured(self) -> None:
        result = CurationStateMachine.transition(CurationStatus.LISTED, CurationStatus.FEATURED)
        assert result == CurationStatus.FEATURED

    def test_valid_transition_featured_to_listed(self) -> None:
        result = CurationStateMachine.transition(CurationStatus.FEATURED, CurationStatus.LISTED)
        assert result == CurationStatus.LISTED

    def test_valid_transition_listed_to_deprecated(self) -> None:
        result = CurationStateMachine.transition(CurationStatus.LISTED, CurationStatus.DEPRECATED)
        assert result == CurationStatus.DEPRECATED

    def test_valid_transition_deprecated_to_unlisted(self) -> None:
        result = CurationStateMachine.transition(
            CurationStatus.DEPRECATED, CurationStatus.UNLISTED
        )
        assert result == CurationStatus.UNLISTED

    def test_valid_transition_unlisted_to_submitted(self) -> None:
        result = CurationStateMachine.transition(CurationStatus.UNLISTED, CurationStatus.SUBMITTED)
        assert result == CurationStatus.SUBMITTED

    def test_invalid_transition_raises(self) -> None:
        with pytest.raises(InvalidCurationTransitionError) as exc_info:
            CurationStateMachine.transition(CurationStatus.DRAFT, CurationStatus.LISTED)
        assert exc_info.value.from_state == CurationStatus.DRAFT
        assert exc_info.value.to_state == CurationStatus.LISTED
        assert "draft" in str(exc_info.value)
        assert "listed" in str(exc_info.value)

    def test_invalid_transition_cannot_skip_review(self) -> None:
        assert not CurationStateMachine.can_transition(
            CurationStatus.SUBMITTED, CurationStatus.APPROVED
        )

    def test_invalid_transition_cannot_go_backwards_approved_to_submitted(self) -> None:
        assert not CurationStateMachine.can_transition(
            CurationStatus.APPROVED, CurationStatus.SUBMITTED
        )

    def test_valid_next_states_from_listed(self) -> None:
        states = CurationStateMachine.valid_next_states(CurationStatus.LISTED)
        assert CurationStatus.FEATURED in states
        assert CurationStatus.DEPRECATED in states
        assert CurationStatus.UNLISTED in states
        assert len(states) == 3

    def test_valid_next_states_from_under_review(self) -> None:
        states = CurationStateMachine.valid_next_states(CurationStatus.UNDER_REVIEW)
        assert CurationStatus.APPROVED in states
        assert CurationStatus.CHANGES_REQUESTED in states
        assert len(states) == 2

    def test_valid_next_states_from_featured(self) -> None:
        states = CurationStateMachine.valid_next_states(CurationStatus.FEATURED)
        assert CurationStatus.LISTED in states
        assert CurationStatus.DEPRECATED in states
        assert CurationStatus.UNLISTED in states


# ============================================================================
# Quality assessment tests
# ============================================================================


class TestAssessPackQuality:
    """Test quality assessment scoring logic."""

    def test_high_quality_pack(self) -> None:
        """A pack with all fields populated and provenance should score high."""
        manifest = _make_manifest()
        provenance = _make_provenance()
        assessment = assess_pack_quality(manifest, provenance)

        assert assessment.overall_score >= 0.70
        assert assessment.label == "high"
        assert assessment.passed is True
        assert len(assessment.checks) == 7

        # Verify each check is present and properly scored
        check_names = {c.name for c in assessment.checks}
        assert check_names == {
            "description_quality",
            "tags_present",
            "category_assigned",
            "license_present",
            "author_present",
            "skills_count",
            "provenance_signed",
        }

    def test_low_quality_pack(self) -> None:
        """A pack with minimal fields should score low."""
        manifest = _make_manifest(
            description="x",  # too short
            author="a",
            license_="",
            tags=[],
            category="",
        )
        assessment = assess_pack_quality(manifest, provenance=None)

        assert assessment.overall_score < 0.45
        assert assessment.label == "low"
        assert assessment.passed is False

        # Verify individual checks
        desc_check = next(c for c in assessment.checks if c.name == "description_quality")
        assert desc_check.passed is False
        assert desc_check.score < 1.0

        tags_check = next(c for c in assessment.checks if c.name == "tags_present")
        assert tags_check.passed is False
        assert tags_check.score == 0.0

    def test_medium_quality_pack(self) -> None:
        """A pack with some fields present should score medium."""
        manifest = _make_manifest(
            description="A reasonable description for a pack",  # 40 chars < 50
            author="tester",
            license_="",  # missing
            tags=["one", "two"],
            category="testing",
        )
        assessment = assess_pack_quality(manifest, provenance=None)

        # With no license and no provenance, but most other fields present
        assert assessment.label in ("medium", "high")
        assert assessment.overall_score >= 0.45

    def test_custom_threshold(self) -> None:
        """Custom threshold changes the passed flag."""
        manifest = _make_manifest()
        # With a very high threshold, even a good pack may fail
        strict = assess_pack_quality(manifest, _make_provenance(), threshold=0.9)
        # With a very low threshold, it should always pass
        lenient = assess_pack_quality(manifest, _make_provenance(), threshold=0.1)
        assert lenient.passed is True
        # Both use the same score, only the passed flag differs
        assert strict.overall_score == lenient.overall_score

    def test_score_bounded_zero_to_one(self) -> None:
        """Scores should always be between 0 and 1."""
        manifest = _make_manifest()
        assessment = assess_pack_quality(manifest, _make_provenance())
        assert 0.0 <= assessment.overall_score <= 1.0
        for check in assessment.checks:
            assert 0.0 <= check.score <= 1.0

    def test_review_signals_expose_blockers_and_recommendations(self) -> None:
        manifest = _make_manifest(
            description="Thin",
            author="a",
            license_="",
            tags=[],
            category="",
        )
        assessment = assess_pack_quality(manifest, provenance=None, threshold=0.5)

        signals = build_curation_review_signals(manifest, assessment, provenance=None)

        assert signals.risk_level == "high"
        assert signals.featured_eligible is False
        assert "provenance_signed" in signals.publish_blockers
        assert any(signal.severity == "blocker" for signal in signals.signals)
        assert any("provenance" in action.lower() for action in signals.recommendations)


# ============================================================================
# CurationService tests
# ============================================================================


class TestCurationService:
    """Test the curation service lifecycle operations."""

    def _make_service(
        self,
        packs: dict[str, _FakeInstalledPack] | None = None,
    ) -> tuple[CurationService, _FakePackRegistry, CategoryRegistry]:
        registry = _FakePackRegistry(packs or {"test-pack": _FakeInstalledPack()})
        cat_registry = CategoryRegistry()
        service = CurationService(registry, cat_registry, min_quality_score=0.3)
        return service, registry, cat_registry

    def test_submit_creates_record(self) -> None:
        svc, _, _ = self._make_service()
        record = svc.submit("test-pack")

        assert record.pack_name == "test-pack"
        assert record.status == CurationStatus.SUBMITTED
        assert record.quality is not None
        assert record.quality.overall_score > 0
        assert record.submitted_at is not None

    def test_submit_unknown_pack_raises(self) -> None:
        svc, _, _ = self._make_service()
        with pytest.raises(ValueError, match="not installed"):
            svc.submit("nonexistent")

    def test_review_approve_and_list(self) -> None:
        """Full lifecycle: submit -> review(approve) -> list."""
        svc, _, _ = self._make_service()
        svc.submit("test-pack")

        # Start review + approve
        svc.start_review("test-pack", "reviewer-1")
        record = svc.complete_review("test-pack", "approved", notes="LGTM")

        assert record.status == CurationStatus.APPROVED
        assert record.reviewer_id == "reviewer-1"
        assert record.review_notes == "LGTM"
        assert record.reviewed_at is not None

        # List
        record = svc.list_pack("test-pack")
        assert record.status == CurationStatus.LISTED
        assert record.listed_at is not None

    def test_review_changes_requested(self) -> None:
        """Review with changes_requested decision."""
        svc, _, _ = self._make_service()
        svc.submit("test-pack")
        svc.start_review("test-pack", "reviewer-1")
        record = svc.complete_review("test-pack", "changes_requested", notes="Fix description")

        assert record.status == CurationStatus.CHANGES_REQUESTED
        assert record.review_notes == "Fix description"

    def test_resubmit_after_changes_requested(self) -> None:
        """A pack in CHANGES_REQUESTED can be resubmitted."""
        svc, _, _ = self._make_service()
        svc.submit("test-pack")
        svc.start_review("test-pack", "reviewer-1")
        svc.complete_review("test-pack", "changes_requested")

        record = svc.submit("test-pack")
        assert record.status == CurationStatus.SUBMITTED

    def test_feature_and_unfeature(self) -> None:
        """Feature/unfeature a listed pack."""
        svc, _, _ = self._make_service()
        svc.submit("test-pack")
        svc.start_review("test-pack", "r1")
        svc.complete_review("test-pack", "approved")
        svc.list_pack("test-pack")

        record = svc.feature("test-pack")
        assert record.status == CurationStatus.FEATURED
        assert record.featured is True
        assert "featured" in record.badges

        record = svc.unfeature("test-pack")
        assert record.status == CurationStatus.LISTED
        assert record.featured is False
        assert "featured" not in record.badges

    def test_verify_adds_badge(self) -> None:
        """Verify adds a verified badge without changing status."""
        svc, _, _ = self._make_service()
        svc.submit("test-pack")

        record = svc.verify("test-pack")
        assert record.verified is True
        assert "verified" in record.badges
        # Status should still be SUBMITTED
        assert record.status == CurationStatus.SUBMITTED

    def test_deprecate_listed_pack(self) -> None:
        """Deprecate a listed pack with a reason."""
        svc, _, _ = self._make_service()
        svc.submit("test-pack")
        svc.start_review("test-pack", "r1")
        svc.complete_review("test-pack", "approved")
        svc.list_pack("test-pack")

        record = svc.deprecate("test-pack", "Superseded by v2")
        assert record.status == CurationStatus.DEPRECATED
        assert record.deprecation_reason == "Superseded by v2"

    def test_unlist_from_deprecated(self) -> None:
        """Unlist a deprecated pack."""
        svc, _, _ = self._make_service()
        svc.submit("test-pack")
        svc.start_review("test-pack", "r1")
        svc.complete_review("test-pack", "approved")
        svc.list_pack("test-pack")
        svc.deprecate("test-pack")

        record = svc.unlist("test-pack")
        assert record.status == CurationStatus.UNLISTED

    def test_unlist_removes_featured_badge(self) -> None:
        """Unlisting removes the featured badge."""
        svc, _, _ = self._make_service()
        svc.submit("test-pack")
        svc.start_review("test-pack", "r1")
        svc.complete_review("test-pack", "approved")
        svc.list_pack("test-pack")
        svc.feature("test-pack")

        record = svc.unlist("test-pack")
        assert record.featured is False
        assert "featured" not in record.badges

    def test_get_curation_returns_none_for_unknown(self) -> None:
        svc, _, _ = self._make_service()
        assert svc.get_curation("nonexistent") is None

    def test_list_curated_with_status_filter(self) -> None:
        """List curated records with status filter."""
        pack_a = _FakeInstalledPack(name="pack-a")
        pack_b = _FakeInstalledPack(name="pack-b")
        svc, registry, _ = self._make_service({"pack-a": pack_a, "pack-b": pack_b})
        svc.submit("pack-a")
        svc.submit("pack-b")
        svc.start_review("pack-a", "r1")
        svc.complete_review("pack-a", "approved")

        submitted = svc.list_curated(status=CurationStatus.SUBMITTED)
        assert len(submitted) == 1
        assert submitted[0].pack_name == "pack-b"

        approved = svc.list_curated(status=CurationStatus.APPROVED)
        assert len(approved) == 1
        assert approved[0].pack_name == "pack-a"

    def test_list_curated_featured_only(self) -> None:
        """List only featured packs."""
        pack_a = _FakeInstalledPack(name="pack-a")
        pack_b = _FakeInstalledPack(name="pack-b")
        svc, _, _ = self._make_service({"pack-a": pack_a, "pack-b": pack_b})

        # Full lifecycle for both packs
        for name in ("pack-a", "pack-b"):
            svc.submit(name)
            svc.start_review(name, "r1")
            svc.complete_review(name, "approved")
            svc.list_pack(name)

        svc.feature("pack-a")

        featured = svc.list_curated(featured_only=True)
        assert len(featured) == 1
        assert featured[0].pack_name == "pack-a"

    def test_assess_quality_without_submitting(self) -> None:
        """Quality assessment should work independently of submission."""
        svc, _, _ = self._make_service()
        assessment = svc.assess_quality("test-pack")
        assert isinstance(assessment, QualityAssessment)
        assert assessment.overall_score > 0

        # No curation record should exist
        assert svc.get_curation("test-pack") is None

    def test_invalid_review_decision_raises(self) -> None:
        """Invalid decision string should be rejected."""
        svc, _, _ = self._make_service()
        svc.submit("test-pack")
        svc.start_review("test-pack", "r1")
        with pytest.raises(ValueError, match="Invalid review decision"):
            svc.complete_review("test-pack", "rejected")

    def test_persistence_round_trip(self) -> None:
        """Records should survive a persistence round-trip."""
        store = _FakeStateStore()
        pack = _FakeInstalledPack()
        registry = _FakePackRegistry({"test-pack": pack})
        cat_reg = CategoryRegistry()

        svc1 = CurationService(registry, cat_reg, store, min_quality_score=0.3)
        svc1.submit("test-pack")
        svc1.start_review("test-pack", "r1")
        svc1.complete_review("test-pack", "approved")

        # Create a new service instance that loads from the same store
        svc2 = CurationService(registry, cat_reg, store, min_quality_score=0.3)
        record = svc2.get_curation("test-pack")
        assert record is not None
        assert record.status == CurationStatus.APPROVED
        assert record.reviewer_id == "r1"


# ============================================================================
# CategoryRegistry tests
# ============================================================================


class TestCategoryRegistry:
    """Test category registry CRUD and persistence."""

    def test_default_categories_seeded(self) -> None:
        """Default categories are seeded from comma-separated string."""
        reg = CategoryRegistry(default_categories_str="automation,devops,testing")
        cats = reg.list_categories()
        assert len(cats) == 3
        slugs = [c.slug for c in cats]
        assert "automation" in slugs
        assert "devops" in slugs
        assert "testing" in slugs

    def test_default_categories_have_labels(self) -> None:
        """Default category labels should be title-cased."""
        reg = CategoryRegistry(default_categories_str="data-analysis")
        cat = reg.get_category("data-analysis")
        assert cat is not None
        assert cat.label == "Data Analysis"

    def test_list_returns_sorted(self) -> None:
        """Categories should be listed in slug order."""
        reg = CategoryRegistry(default_categories_str="z-cat,a-cat,m-cat")
        cats = reg.list_categories()
        assert [c.slug for c in cats] == ["a-cat", "m-cat", "z-cat"]

    def test_add_category(self) -> None:
        reg = CategoryRegistry()
        reg.add_category(
            MarketplaceCategory(slug="custom", label="Custom", description="Custom category")
        )
        cat = reg.get_category("custom")
        assert cat is not None
        assert cat.label == "Custom"

    def test_add_duplicate_raises(self) -> None:
        reg = CategoryRegistry(default_categories_str="testing")
        with pytest.raises(ValueError, match="already exists"):
            reg.add_category(MarketplaceCategory(slug="testing", label="Testing"))

    def test_update_category(self) -> None:
        reg = CategoryRegistry(default_categories_str="testing")
        updated = reg.update_category(
            "testing", label="QA Testing", description="Quality assurance packs"
        )
        assert updated.label == "QA Testing"
        assert updated.description == "Quality assurance packs"

        # Verify persistence in registry
        reloaded = reg.get_category("testing")
        assert reloaded is not None
        assert reloaded.label == "QA Testing"

    def test_update_nonexistent_raises(self) -> None:
        reg = CategoryRegistry()
        with pytest.raises(ValueError, match="not found"):
            reg.update_category("nonexistent", label="Nope")

    def test_remove_category(self) -> None:
        reg = CategoryRegistry(default_categories_str="testing,devops")
        reg.remove_category("testing")
        assert reg.get_category("testing") is None
        assert len(reg.list_categories()) == 1

    def test_remove_nonexistent_raises(self) -> None:
        reg = CategoryRegistry()
        with pytest.raises(ValueError, match="not found"):
            reg.remove_category("nonexistent")

    def test_persistence_round_trip(self) -> None:
        """Categories should survive a persistence round-trip."""
        store = _FakeStateStore()

        reg1 = CategoryRegistry(store, "testing,devops")
        reg1.add_category(MarketplaceCategory(slug="custom", label="Custom"))

        reg2 = CategoryRegistry(store)
        cats = reg2.list_categories()
        slugs = [c.slug for c in cats]
        assert "testing" in slugs
        assert "devops" in slugs
        assert "custom" in slugs

    def test_get_nonexistent_returns_none(self) -> None:
        reg = CategoryRegistry()
        assert reg.get_category("nonexistent") is None


# ============================================================================
# API route tests
# ============================================================================


def _create_curation_test_app() -> TestClient:
    """Build a minimal FastAPI app with curation services wired in."""
    from fastapi import FastAPI
    from starlette.middleware.base import BaseHTTPMiddleware

    from agent33.api.routes.marketplace import router

    test_app = FastAPI()

    # Mock auth middleware: inject a fake user with necessary scopes
    class FakeAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Any, call_next: Any) -> Any:
            user = MagicMock()
            user.tenant_id = "test-tenant"
            user.scopes = ["agents:read", "agents:write", "admin"]
            request.state.user = user
            return await call_next(request)

    test_app.add_middleware(FakeAuthMiddleware)
    test_app.include_router(router)

    pack = _FakeInstalledPack()
    registry = _FakePackRegistry({"test-pack": pack})
    cat_registry = CategoryRegistry(default_categories_str="testing,devops")
    svc = CurationService(registry, cat_registry, min_quality_score=0.3)

    test_app.state.curation_service = svc
    test_app.state.category_registry = cat_registry
    test_app.state.pack_registry = registry
    test_app.state.pack_marketplace = None

    return TestClient(test_app)


@pytest.fixture()
def _curation_app() -> TestClient:
    return _create_curation_test_app()


class TestCurationAPI:
    """Test curation API endpoints."""

    def test_submit_for_curation(self, _curation_app: TestClient) -> None:
        resp = _curation_app.post(
            "/v1/marketplace/curation/submit",
            json={"pack_name": "test-pack"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["pack_name"] == "test-pack"
        assert data["status"] == "submitted"
        assert data["quality"] is not None
        assert data["review_signals"] is not None
        assert data["review_signals"]["pack_name"] == "test-pack"
        assert data["quality"]["overall_score"] > 0

    def test_submit_nonexistent_pack(self, _curation_app: TestClient) -> None:
        resp = _curation_app.post(
            "/v1/marketplace/curation/submit",
            json={"pack_name": "no-such-pack"},
        )
        assert resp.status_code == 400
        assert "not installed" in resp.json()["detail"]

    def test_get_curation_record(self, _curation_app: TestClient) -> None:
        _curation_app.post(
            "/v1/marketplace/curation/submit",
            json={"pack_name": "test-pack"},
        )
        resp = _curation_app.get("/v1/marketplace/curation/test-pack")
        assert resp.status_code == 200
        data = resp.json()
        assert data["pack_name"] == "test-pack"
        assert data["status"] == "submitted"

    def test_get_curation_record_not_found(self, _curation_app: TestClient) -> None:
        resp = _curation_app.get("/v1/marketplace/curation/nonexistent")
        assert resp.status_code == 404

    def test_list_curated(self, _curation_app: TestClient) -> None:
        _curation_app.post(
            "/v1/marketplace/curation/submit",
            json={"pack_name": "test-pack"},
        )
        resp = _curation_app.get("/v1/marketplace/curation")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert len(data["records"]) == 1

    def test_list_curated_with_status_filter(self, _curation_app: TestClient) -> None:
        _curation_app.post(
            "/v1/marketplace/curation/submit",
            json={"pack_name": "test-pack"},
        )
        resp = _curation_app.get("/v1/marketplace/curation?status=submitted")
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

        resp = _curation_app.get("/v1/marketplace/curation?status=approved")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_list_curated_invalid_status(self, _curation_app: TestClient) -> None:
        resp = _curation_app.get("/v1/marketplace/curation?status=bogus")
        assert resp.status_code == 400

    def test_review_approve(self, _curation_app: TestClient) -> None:
        _curation_app.post(
            "/v1/marketplace/curation/submit",
            json={"pack_name": "test-pack"},
        )
        resp = _curation_app.post(
            "/v1/marketplace/curation/test-pack/review",
            json={
                "decision": "approved",
                "reviewer_id": "admin-1",
                "notes": "Looks good",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "approved"
        assert data["reviewer_id"] == "admin-1"
        assert data["review_notes"] == "Looks good"

    def test_review_changes_requested(self, _curation_app: TestClient) -> None:
        _curation_app.post(
            "/v1/marketplace/curation/submit",
            json={"pack_name": "test-pack"},
        )
        resp = _curation_app.post(
            "/v1/marketplace/curation/test-pack/review",
            json={
                "decision": "changes_requested",
                "reviewer_id": "admin-1",
                "notes": "Needs better description",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "changes_requested"

    def test_feature_toggle(self, _curation_app: TestClient) -> None:
        # Submit -> review -> list -> feature
        _curation_app.post(
            "/v1/marketplace/curation/submit",
            json={"pack_name": "test-pack"},
        )
        _curation_app.post(
            "/v1/marketplace/curation/test-pack/review",
            json={"decision": "approved", "reviewer_id": "admin-1"},
        )
        # List the pack
        svc = _curation_app.app.state.curation_service  # type: ignore[union-attr]
        svc.list_pack("test-pack")

        # Feature
        resp = _curation_app.post("/v1/marketplace/curation/test-pack/feature")
        assert resp.status_code == 200
        assert resp.json()["status"] == "featured"
        assert resp.json()["featured"] is True

        # Unfeature (toggle)
        resp = _curation_app.post("/v1/marketplace/curation/test-pack/feature")
        assert resp.status_code == 200
        assert resp.json()["status"] == "listed"
        assert resp.json()["featured"] is False

    def test_verify_pack(self, _curation_app: TestClient) -> None:
        _curation_app.post(
            "/v1/marketplace/curation/submit",
            json={"pack_name": "test-pack"},
        )
        resp = _curation_app.post("/v1/marketplace/curation/test-pack/verify")
        assert resp.status_code == 200
        data = resp.json()
        assert data["verified"] is True
        assert "verified" in data["badges"]

    def test_deprecate_pack(self, _curation_app: TestClient) -> None:
        # Submit -> review -> list -> deprecate
        _curation_app.post(
            "/v1/marketplace/curation/submit",
            json={"pack_name": "test-pack"},
        )
        _curation_app.post(
            "/v1/marketplace/curation/test-pack/review",
            json={"decision": "approved", "reviewer_id": "admin-1"},
        )
        svc = _curation_app.app.state.curation_service  # type: ignore[union-attr]
        svc.list_pack("test-pack")

        resp = _curation_app.post(
            "/v1/marketplace/curation/test-pack/deprecate",
            json={"reason": "Replaced by v2"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deprecated"
        assert data["deprecation_reason"] == "Replaced by v2"

    def test_quality_assessment(self, _curation_app: TestClient) -> None:
        resp = _curation_app.get("/v1/marketplace/quality/test-pack")
        assert resp.status_code == 200
        data = resp.json()
        assert "overall_score" in data
        assert "label" in data
        assert "checks" in data
        assert len(data["checks"]) == 7

    def test_quality_review_signals(self, _curation_app: TestClient) -> None:
        registry = _curation_app.app.state.pack_registry  # type: ignore[union-attr]
        registry.add(
            _FakeInstalledPack(
                name="thin-pack",
                description="Thin",
                author="a",
                pack_license="",
                tags=[],
                category="",
            )
        )

        resp = _curation_app.get("/v1/marketplace/quality/thin-pack/review-signals")

        assert resp.status_code == 200
        data = resp.json()
        assert data["pack_name"] == "thin-pack"
        assert data["risk_level"] == "high"
        assert data["featured_eligible"] is False
        assert "provenance_signed" in data["publish_blockers"]
        assert any(signal["id"] == "description_quality" for signal in data["signals"])

    def test_quality_assessment_nonexistent(self, _curation_app: TestClient) -> None:
        resp = _curation_app.get("/v1/marketplace/quality/nonexistent")
        assert resp.status_code == 400

    def test_list_featured(self, _curation_app: TestClient) -> None:
        resp = _curation_app.get("/v1/marketplace/featured")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_list_categories(self, _curation_app: TestClient) -> None:
        resp = _curation_app.get("/v1/marketplace/categories")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        slugs = [c["slug"] for c in data["categories"]]
        assert "testing" in slugs
        assert "devops" in slugs

    def test_create_category(self, _curation_app: TestClient) -> None:
        resp = _curation_app.post(
            "/v1/marketplace/categories",
            json={
                "slug": "security",
                "label": "Security",
                "description": "Security packs",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["slug"] == "security"
        assert data["label"] == "Security"

    def test_create_duplicate_category(self, _curation_app: TestClient) -> None:
        resp = _curation_app.post(
            "/v1/marketplace/categories",
            json={"slug": "testing", "label": "Testing"},
        )
        assert resp.status_code == 409

    def test_update_category(self, _curation_app: TestClient) -> None:
        resp = _curation_app.put(
            "/v1/marketplace/categories/testing",
            json={"label": "QA Testing", "description": "Updated desc"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["label"] == "QA Testing"
        assert data["description"] == "Updated desc"

    def test_update_nonexistent_category(self, _curation_app: TestClient) -> None:
        resp = _curation_app.put(
            "/v1/marketplace/categories/nonexistent",
            json={"label": "Nope"},
        )
        assert resp.status_code == 404

    def test_delete_category(self, _curation_app: TestClient) -> None:
        resp = _curation_app.delete("/v1/marketplace/categories/testing")
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted"] is True
        assert data["slug"] == "testing"

        # Verify it's gone
        resp = _curation_app.get("/v1/marketplace/categories")
        slugs = [c["slug"] for c in resp.json()["categories"]]
        assert "testing" not in slugs

    def test_delete_nonexistent_category(self, _curation_app: TestClient) -> None:
        resp = _curation_app.delete("/v1/marketplace/categories/nonexistent")
        assert resp.status_code == 404
