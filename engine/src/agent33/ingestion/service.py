"""Ingestion service: business operations on CandidateAsset records.

Provides the application-level entry points for the candidate lifecycle.
All status transitions are delegated to ``CandidateStateMachine``; no
inline status comparisons are performed here.

Persistence is optional: when a ``IngestionPersistence`` instance is
supplied, every mutation is written through to SQLite so state survives
process restarts.  Without it the service operates purely in-memory.

CLEAN-ROOM RESTRICTION
=======================
No code in this file may originate from the EvoMap/Evolver project.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from agent33.ingestion.models import CandidateAsset, CandidateStatus, ConfidenceLevel
from agent33.ingestion.state_machine import CandidateStateMachine

if TYPE_CHECKING:
    from agent33.ingestion.journal import TransitionJournal
    from agent33.ingestion.notifications import IngestionNotificationService
    from agent33.ingestion.persistence import IngestionPersistence
    from agent33.skills.registry import SkillRegistry

logger = structlog.get_logger()

_state_machine = CandidateStateMachine()


class IngestionService:
    """Application service for the candidate asset ingestion lifecycle.

    When constructed with a ``persistence`` argument the service writes every
    mutation to SQLite and re-hydrates its in-memory store from the DB on
    startup, so state survives process restarts.

    When constructed with a ``journal`` argument every successful lifecycle
    transition is appended to the audit journal.

    Without ``persistence`` the service is purely in-memory (backwards
    compatible with unit tests that do not need a DB).
    """

    def __init__(
        self,
        *,
        persistence: IngestionPersistence | None = None,
        journal: TransitionJournal | None = None,
        notifications: IngestionNotificationService | None = None,
        skill_registry: SkillRegistry | None = None,
    ) -> None:
        self._store: dict[str, CandidateAsset] = {}
        self._persistence = persistence
        self._journal = journal
        self._notifications = notifications
        self._skill_registry = skill_registry
        if persistence is not None:
            self._hydrate_from_persistence()

    # ------------------------------------------------------------------
    # Startup hydration
    # ------------------------------------------------------------------

    def _hydrate_from_persistence(self) -> None:
        """Re-populate the in-memory store from every persisted asset.

        All assets in the DB (regardless of status) are loaded so that
        ``get()`` and ``list_by_*`` queries work without hitting SQLite
        for every call.
        """
        if self._persistence is None:
            return
        for status in CandidateStatus:
            for asset in self._persistence.load_by_status(status):
                self._store[asset.id] = asset
                self._register_published_skill(asset, source="hydrate")
        logger.info("ingestion_store_hydrated", count=len(self._store))

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def ingest(
        self,
        *,
        name: str,
        asset_type: str,
        source_uri: str | None,
        tenant_id: str,
        confidence: ConfidenceLevel = ConfidenceLevel.LOW,
        metadata: dict[str, Any] | None = None,
    ) -> CandidateAsset:
        """Create a new candidate asset in ``CANDIDATE`` status.

        The caller cannot bypass the initial ``CANDIDATE`` status; all new
        assets enter the lifecycle at its first stage per architectural
        decision #18.

        Args:
            name: Human-readable asset name (1–128 chars).
            asset_type: Category: ``"skill"``, ``"pack"``, ``"workflow"``, or
                ``"tool"``.
            source_uri: URI identifying the upstream source, if known.
            tenant_id: Tenant scope for this record.
            confidence: Trust label; defaults to ``LOW`` for all external intake.
            metadata: Arbitrary key/value metadata.

        Returns:
            The newly created ``CandidateAsset``.
        """
        now = datetime.now(UTC)
        asset = CandidateAsset(
            id=str(uuid.uuid4()),
            name=name,
            asset_type=asset_type,
            status=CandidateStatus.CANDIDATE,
            confidence=confidence,
            source_uri=source_uri,
            tenant_id=tenant_id,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )
        self._store[asset.id] = asset
        if self._persistence is not None:
            self._persistence.save(asset)
        if self._journal is not None:
            self._journal.record_event(
                asset,
                event_type="ingested",
                operator="system",
                reason="Asset entered the ingestion lifecycle.",
                details={
                    "asset_type": asset.asset_type,
                    "confidence": asset.confidence.value,
                    "source_uri": asset.source_uri,
                },
            )
        if asset.metadata.get("review_required") is True:
            if self._journal is not None:
                self._journal.record_event(
                    asset,
                    event_type="review_required",
                    operator="intake_pipeline",
                    reason="Asset requires operator review before promotion.",
                    details={"review_required": True},
                )
            if self._notifications is not None:
                from agent33.ingestion.notifications import IngestionNotificationEvent

                self._notifications.emit(
                    asset,
                    event_type=IngestionNotificationEvent.REVIEW_REQUIRED,
                    operator="intake_pipeline",
                    reason="Asset requires operator review before promotion.",
                    details={"review_required": True},
                )
        if asset.metadata.get("quarantine") is True:
            if self._journal is not None:
                self._journal.record_event(
                    asset,
                    event_type="quarantined",
                    operator="intake_pipeline",
                    reason="Asset was quarantined for manual inspection.",
                    details={"quarantine": True},
                )
            if self._notifications is not None:
                from agent33.ingestion.notifications import IngestionNotificationEvent

                self._notifications.emit(
                    asset,
                    event_type=IngestionNotificationEvent.QUARANTINED,
                    operator="intake_pipeline",
                    reason="Asset was quarantined for manual inspection.",
                    details={"quarantine": True},
                )
        logger.info("ingestion_asset_ingested", asset_id=asset.id, tenant_id=tenant_id)
        return asset

    def validate(
        self,
        asset_id: str,
        *,
        operator: str | None = None,
        reason: str = "validated",
    ) -> CandidateAsset:
        """Transition an asset from ``CANDIDATE`` to ``VALIDATED``.

        Raises:
            KeyError: Asset not found.
            CandidateTransitionError: Asset is not in ``CANDIDATE`` status.
        """
        asset = self._require(asset_id)
        old_status = asset.status
        updated = _state_machine.transition(
            asset,
            CandidateStatus.VALIDATED,
            operator=operator,
        )
        self._store[asset_id] = updated
        if self._persistence is not None:
            self._persistence.save(updated)
        if self._journal is not None:
            self._journal.record(
                updated,
                old_status,
                operator=operator or "system",
                reason=reason,
            )
        logger.info("ingestion_asset_validated", asset_id=asset_id, operator=operator)
        return updated

    def promote(
        self,
        asset_id: str,
        *,
        operator: str | None = None,
        reason: str = "promoted",
    ) -> CandidateAsset:
        """Transition an asset from ``VALIDATED`` to ``PUBLISHED``.

        Raises:
            KeyError: Asset not found.
            CandidateTransitionError: Asset is not in ``VALIDATED`` status.
        """
        asset = self._require(asset_id)
        old_status = asset.status
        updated = _state_machine.transition(
            asset,
            CandidateStatus.PUBLISHED,
            operator=operator,
        )
        self._store[asset_id] = updated
        if self._persistence is not None:
            self._persistence.save(updated)
        if self._journal is not None:
            self._journal.record(
                updated,
                old_status,
                operator=operator or "system",
                reason=reason,
            )
        self._register_published_skill(updated, source="promote")
        logger.info("ingestion_asset_promoted", asset_id=asset_id, operator=operator)
        return updated

    def revoke(
        self,
        asset_id: str,
        *,
        reason: str,
        operator: str | None = None,
    ) -> CandidateAsset:
        """Transition an asset to ``REVOKED`` status.

        ``reason`` is required on revocation and is stored on the record for
        operator audit purposes.

        Raises:
            KeyError: Asset not found.
            CandidateTransitionError: Asset is already in ``REVOKED`` status (terminal).
        """
        asset = self._require(asset_id)
        old_status = asset.status
        updated = _state_machine.transition(
            asset,
            CandidateStatus.REVOKED,
            operator=operator,
            reason=reason,
        )
        self._store[asset_id] = updated
        if self._persistence is not None:
            self._persistence.save(updated)
        if self._journal is not None:
            self._journal.record(
                updated,
                old_status,
                operator=operator or "system",
                reason=reason,
            )
        logger.info("ingestion_asset_revoked", asset_id=asset_id, operator=operator)
        return updated

    def patch_metadata(
        self,
        asset_id: str,
        updates: dict[str, Any],
    ) -> CandidateAsset:
        """Merge *updates* into the asset's metadata and persist the result.

        Existing keys not present in *updates* are preserved.  This is used
        by the intake pipeline to attach routing flags (``review_required``,
        ``quarantine``) without going through a lifecycle transition.

        Args:
            asset_id: ID of the asset to update.
            updates: Key/value pairs to merge into the existing metadata.

        Returns:
            The updated ``CandidateAsset``.

        Raises:
            KeyError: Asset not found.
        """
        asset = self._require(asset_id)
        merged = {**asset.metadata, **updates}
        updated = asset.model_copy(update={"metadata": merged, "updated_at": datetime.now(UTC)})
        self._store[asset_id] = updated
        if self._persistence is not None:
            self._persistence.save(updated)
        prior_review_required = asset.metadata.get("review_required") is True
        review_required = merged.get("review_required") is True
        prior_quarantine = asset.metadata.get("quarantine") is True
        quarantine = merged.get("quarantine") is True
        if self._journal is not None and not prior_review_required and review_required:
            self._journal.record_event(
                updated,
                event_type="review_required",
                operator="intake_pipeline",
                reason="Asset requires operator review before promotion.",
                details={"review_required": True},
            )
        if self._notifications is not None and not prior_review_required and review_required:
            from agent33.ingestion.notifications import IngestionNotificationEvent

            self._notifications.emit(
                updated,
                event_type=IngestionNotificationEvent.REVIEW_REQUIRED,
                operator="intake_pipeline",
                reason="Asset requires operator review before promotion.",
                details={"review_required": True},
            )
        if self._journal is not None and not prior_quarantine and quarantine:
            self._journal.record_event(
                updated,
                event_type="quarantined",
                operator="intake_pipeline",
                reason="Asset was quarantined for manual inspection.",
                details={"quarantine": True},
            )
        if self._notifications is not None and not prior_quarantine and quarantine:
            from agent33.ingestion.notifications import IngestionNotificationEvent

            self._notifications.emit(
                updated,
                event_type=IngestionNotificationEvent.QUARANTINED,
                operator="intake_pipeline",
                reason="Asset was quarantined for manual inspection.",
                details={"quarantine": True},
            )
        logger.info("ingestion_asset_metadata_patched", asset_id=asset_id)
        return updated

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get(self, asset_id: str) -> CandidateAsset | None:
        """Return the asset with the given id, or None if not found."""
        return self._store.get(asset_id)

    def list_by_status(self, status: CandidateStatus) -> list[CandidateAsset]:
        """Return all assets in the given lifecycle status."""
        return [a for a in self._store.values() if a.status == status]

    def list_by_tenant(self, tenant_id: str) -> list[CandidateAsset]:
        """Return all assets belonging to the given tenant."""
        return [a for a in self._store.values() if a.tenant_id == tenant_id]

    def get_journal(self, asset_id: str) -> list[dict[str, Any]]:
        """Return all journal entries for the given asset, or empty list if no journal."""
        if self._journal is None:
            return []
        return self._journal.entries_for(asset_id)

    def get_tenant_journal(self, tenant_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return the most-recent ``limit`` journal entries for the given tenant."""
        if self._journal is None:
            return []
        return self._journal.entries_for_tenant(tenant_id, limit=limit)

    # ------------------------------------------------------------------
    # Operator review queue
    # ------------------------------------------------------------------

    def list_pending_review(self, tenant_id: str) -> list[CandidateAsset]:
        """Return CANDIDATE assets that require operator review for the given tenant.

        An asset is pending review when its metadata contains
        ``review_required == True`` and its status is ``CANDIDATE``.
        """
        return [
            a
            for a in self.list_by_tenant(tenant_id)
            if a.status == CandidateStatus.CANDIDATE and a.metadata.get("review_required") is True
        ]

    def approve(
        self,
        asset_id: str,
        *,
        operator: str,
        reason: str,
    ) -> CandidateAsset:
        """Approve a candidate asset: validate it and clear review/quarantine flags.

        Calls ``validate()`` to advance to VALIDATED, then clears
        ``review_required`` and ``quarantine`` from metadata.

        Raises:
            KeyError: Asset not found.
            CandidateTransitionError: Asset is not in ``CANDIDATE`` status.
        """
        self.validate(asset_id, operator=operator, reason=reason)
        cleared = self.patch_metadata(
            asset_id,
            {"review_required": False, "quarantine": False},
        )
        if self._journal is not None:
            self._journal.record_event(
                cleared,
                event_type="approved",
                operator=operator,
                reason=reason,
                details={"review_required": False, "quarantine": False},
            )
        if self._notifications is not None:
            from agent33.ingestion.notifications import IngestionNotificationEvent

            self._notifications.emit(
                cleared,
                event_type=IngestionNotificationEvent.APPROVED,
                operator=operator,
                reason=reason,
                details={"review_required": False, "quarantine": False},
            )
        logger.info("ingestion_asset_approved", asset_id=asset_id, operator=operator)
        return cleared

    def reject(
        self,
        asset_id: str,
        *,
        operator: str,
        reason: str,
    ) -> CandidateAsset:
        """Reject a candidate asset by revoking it.

        Raises:
            KeyError: Asset not found.
            CandidateTransitionError: Asset is in a terminal state.
        """
        revoked = self.revoke(asset_id, reason=reason, operator=operator)
        if self._journal is not None:
            self._journal.record_event(
                revoked,
                event_type="rejected",
                operator=operator,
                reason=reason,
            )
        if self._notifications is not None:
            from agent33.ingestion.notifications import IngestionNotificationEvent

            self._notifications.emit(
                revoked,
                event_type=IngestionNotificationEvent.REJECTED,
                operator=operator,
                reason=reason,
            )
        logger.info("ingestion_asset_rejected", asset_id=asset_id, operator=operator)
        return revoked

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require(self, asset_id: str) -> CandidateAsset:
        """Return the asset or raise KeyError."""
        asset = self._store.get(asset_id)
        if asset is None:
            raise KeyError(asset_id)
        return asset

    def _register_published_skill(self, asset: CandidateAsset, *, source: str) -> None:
        if self._skill_registry is None or asset.asset_type != "skill":
            return

        from agent33.skills.ingestion import skill_definition_from_candidate_asset

        try:
            skill = skill_definition_from_candidate_asset(asset)
        except (OSError, ValueError) as exc:
            logger.warning(
                "ingestion_skill_registration_failed",
                asset_id=asset.id,
                asset_name=asset.name,
                source=source,
                error=str(exc),
            )
            return

        if skill is None:
            logger.info(
                "ingestion_skill_registration_skipped",
                asset_id=asset.id,
                asset_name=asset.name,
                source=source,
                reason="no loadable skill definition",
            )
            return

        self._skill_registry.register(skill)
        logger.info(
            "ingestion_skill_registered",
            asset_id=asset.id,
            asset_name=asset.name,
            source=source,
            skill_name=skill.name,
        )
