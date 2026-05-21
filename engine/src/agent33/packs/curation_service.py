"""Curation service: orchestrates the curation lifecycle for marketplace packs.

Manages submission, review, listing, featuring, verification, deprecation,
and quality assessment with state-store persistence.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from agent33.packs.categories import CategoryRegistry

from agent33.packs.curation import (
    CurationRecord,
    CurationReviewSignals,
    CurationStateMachine,
    CurationStatus,
    QualityAssessment,
    assess_pack_quality,
    build_curation_review_signals,
)

logger = structlog.get_logger()


class CurationService:
    """Orchestrate marketplace pack curation lifecycle."""

    def __init__(
        self,
        pack_registry: Any,
        category_registry: CategoryRegistry,
        state_store: Any | None = None,
        min_quality_score: float = 0.5,
        require_review: bool = True,
        *,
        namespace: str = "pack_curation",
    ) -> None:
        self._pack_registry = pack_registry
        self._category_registry = category_registry
        self._state_store = state_store
        self._min_quality_score = min_quality_score
        self._require_review = require_review
        self._namespace = namespace
        self._records: dict[str, CurationRecord] = {}
        self._load()

    # -- Submission ---------------------------------------------------------

    def submit(self, pack_name: str, version: str = "") -> CurationRecord:
        """Submit a pack for curation review.

        Creates a curation record in SUBMITTED status with quality assessment.
        If a record already exists in UNLISTED or CHANGES_REQUESTED state,
        it transitions back to SUBMITTED.
        """
        pack = self._pack_registry.get(pack_name)
        if pack is None:
            raise ValueError(f"Pack '{pack_name}' is not installed")

        manifest = self._manifest_from_pack(pack)
        provenance = getattr(pack, "provenance", None)
        quality = assess_pack_quality(manifest, provenance, threshold=self._min_quality_score)
        review_signals = build_curation_review_signals(manifest, quality, provenance)

        existing = self._records.get(pack_name)
        if existing is not None and existing.status in (
            CurationStatus.UNLISTED,
            CurationStatus.CHANGES_REQUESTED,
        ):
            CurationStateMachine.transition(existing.status, CurationStatus.SUBMITTED)
            existing.status = CurationStatus.SUBMITTED
            existing.version = version or pack.version
            existing.quality = quality
            existing.review_signals = review_signals
            existing.submitted_at = datetime.now(UTC)
            self._persist()
            logger.info("pack_resubmitted", pack_name=pack_name)
            return existing

        record = CurationRecord(
            pack_name=pack_name,
            version=version or pack.version,
            status=CurationStatus.SUBMITTED,
            quality=quality,
            review_signals=review_signals,
            submitted_at=datetime.now(UTC),
        )
        self._records[pack_name] = record
        self._persist()
        logger.info("pack_submitted_for_curation", pack_name=pack_name)
        return record

    # -- Review lifecycle ---------------------------------------------------

    def start_review(self, pack_name: str, reviewer_id: str) -> CurationRecord:
        """Advance a submitted pack to UNDER_REVIEW."""
        record = self._require_record(pack_name)
        CurationStateMachine.transition(record.status, CurationStatus.UNDER_REVIEW)
        record.status = CurationStatus.UNDER_REVIEW
        record.reviewer_id = reviewer_id
        self._persist()
        logger.info("pack_review_started", pack_name=pack_name, reviewer=reviewer_id)
        return record

    def complete_review(
        self,
        pack_name: str,
        decision: str,
        notes: str = "",
        reviewer_id: str = "",
    ) -> CurationRecord:
        """Complete a review with APPROVED or CHANGES_REQUESTED decision."""
        record = self._require_record(pack_name)
        if decision == "approved":
            target = CurationStatus.APPROVED
        elif decision == "changes_requested":
            target = CurationStatus.CHANGES_REQUESTED
        else:
            raise ValueError(f"Invalid review decision: {decision!r}")

        CurationStateMachine.transition(record.status, target)
        record.status = target
        record.review_notes = notes
        if reviewer_id:
            record.reviewer_id = reviewer_id
        record.reviewed_at = datetime.now(UTC)
        self._persist()
        logger.info("pack_review_completed", pack_name=pack_name, decision=decision)
        return record

    # -- Listing ------------------------------------------------------------

    def list_pack(self, pack_name: str) -> CurationRecord:
        """Advance an APPROVED pack to LISTED."""
        record = self._require_record(pack_name)
        CurationStateMachine.transition(record.status, CurationStatus.LISTED)
        record.status = CurationStatus.LISTED
        record.listed_at = datetime.now(UTC)
        self._persist()
        logger.info("pack_listed", pack_name=pack_name)
        return record

    # -- Featured / Unfeatured ---------------------------------------------

    def feature(self, pack_name: str) -> CurationRecord:
        """Mark a LISTED pack as FEATURED."""
        record = self._require_record(pack_name)
        CurationStateMachine.transition(record.status, CurationStatus.FEATURED)
        record.status = CurationStatus.FEATURED
        record.featured = True
        if "featured" not in record.badges:
            record.badges.append("featured")
        self._persist()
        logger.info("pack_featured", pack_name=pack_name)
        return record

    def unfeature(self, pack_name: str) -> CurationRecord:
        """Remove FEATURED status, reverting to LISTED."""
        record = self._require_record(pack_name)
        CurationStateMachine.transition(record.status, CurationStatus.LISTED)
        record.status = CurationStatus.LISTED
        record.featured = False
        if "featured" in record.badges:
            record.badges.remove("featured")
        self._persist()
        logger.info("pack_unfeatured", pack_name=pack_name)
        return record

    # -- Verification -------------------------------------------------------

    def verify(self, pack_name: str) -> CurationRecord:
        """Mark a pack as verified (adds badge, does not change status)."""
        record = self._require_record(pack_name)
        record.verified = True
        if "verified" not in record.badges:
            record.badges.append("verified")
        self._persist()
        logger.info("pack_verified", pack_name=pack_name)
        return record

    # -- Deprecation / Unlisting -------------------------------------------

    def deprecate(self, pack_name: str, reason: str = "") -> CurationRecord:
        """Deprecate a listed or featured pack."""
        record = self._require_record(pack_name)
        CurationStateMachine.transition(record.status, CurationStatus.DEPRECATED)
        record.status = CurationStatus.DEPRECATED
        record.deprecation_reason = reason
        self._persist()
        logger.info("pack_deprecated", pack_name=pack_name, reason=reason)
        return record

    def unlist(self, pack_name: str) -> CurationRecord:
        """Unlist a pack from the marketplace."""
        record = self._require_record(pack_name)
        CurationStateMachine.transition(record.status, CurationStatus.UNLISTED)
        record.status = CurationStatus.UNLISTED
        record.featured = False
        if "featured" in record.badges:
            record.badges.remove("featured")
        self._persist()
        logger.info("pack_unlisted", pack_name=pack_name)
        return record

    # -- Query --------------------------------------------------------------

    def get_curation(self, pack_name: str) -> CurationRecord | None:
        """Look up a curation record by pack name."""
        return self._records.get(pack_name)

    def list_curated(
        self,
        *,
        status: CurationStatus | None = None,
        featured_only: bool = False,
    ) -> list[CurationRecord]:
        """List curation records with optional filters."""
        results: list[CurationRecord] = []
        for record in self._records.values():
            if status is not None and record.status != status:
                continue
            if featured_only and not record.featured:
                continue
            results.append(record)
        return sorted(results, key=lambda r: r.pack_name)

    def assess_quality(self, pack_name: str) -> QualityAssessment:
        """Run quality assessment without submitting."""
        pack = self._pack_registry.get(pack_name)
        if pack is None:
            raise ValueError(f"Pack '{pack_name}' is not installed")

        manifest = self._manifest_from_pack(pack)
        provenance = getattr(pack, "provenance", None)
        return assess_pack_quality(manifest, provenance, threshold=self._min_quality_score)

    def review_signals(self, pack_name: str) -> CurationReviewSignals:
        """Return operator-facing review signals for a pack without changing lifecycle state."""
        pack = self._pack_registry.get(pack_name)
        if pack is None:
            raise ValueError(f"Pack '{pack_name}' is not installed")
        manifest = self._manifest_from_pack(pack)
        provenance = getattr(pack, "provenance", None)
        quality = assess_pack_quality(manifest, provenance, threshold=self._min_quality_score)
        return build_curation_review_signals(manifest, quality, provenance)

    # -- Helpers ------------------------------------------------------------

    def _require_record(self, pack_name: str) -> CurationRecord:
        """Look up a curation record, raising if not found."""
        record = self._records.get(pack_name)
        if record is None:
            raise ValueError(f"No curation record for pack '{pack_name}'")
        return record

    @staticmethod
    def _manifest_from_pack(pack: Any) -> Any:
        from agent33.packs.manifest import PackManifest
        from agent33.packs.models import PackSkillEntry

        return PackManifest(
            name=pack.name,
            version=pack.version,
            description=pack.description,
            author=pack.author,
            license=pack.license,
            tags=list(pack.tags),
            category=pack.category,
            skills=[
                PackSkillEntry(name=s.name, path=s.path, description=s.description)
                for s in pack.skills
            ],
        )

    # -- Persistence --------------------------------------------------------

    def _load(self) -> None:
        if self._state_store is None:
            return
        payload = self._state_store.read_namespace(self._namespace)
        if not payload:
            return
        raw_records = payload.get("records", {})
        if not isinstance(raw_records, dict):
            return
        for name, entry in raw_records.items():
            if not isinstance(name, str) or not isinstance(entry, dict):
                continue
            try:
                self._records[name] = CurationRecord.model_validate(entry)
            except Exception:
                continue

    def _persist(self) -> None:
        if self._state_store is None:
            return
        self._state_store.write_namespace(
            self._namespace,
            {
                "records": {
                    name: record.model_dump(mode="json") for name, record in self._records.items()
                }
            },
        )
