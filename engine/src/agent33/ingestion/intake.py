"""Intake pipeline for external/lower-confidence candidate assets.

Accepts raw asset payloads, routes them by confidence level, and
delegates persistence to ``IngestionService``.  No external HTTP calls
are performed.

Confidence routing:
- HIGH   → auto-advance to VALIDATED
- MEDIUM → stay at CANDIDATE; set ``review_required=True`` in metadata
- LOW    → stay at CANDIDATE; set ``review_required=True`` and
           ``quarantine=True`` in metadata

CLEAN-ROOM RESTRICTION
=======================
No code in this file may originate from the EvoMap/Evolver project.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from agent33.ingestion.models import CandidateAsset, CandidateStatus, ConfidenceLevel

if TYPE_CHECKING:
    from agent33.ingestion.service import IngestionService

logger = structlog.get_logger()


class IntakePipeline:
    """Pipeline that accepts external assets and routes them by confidence.

    Args:
        service: The ``IngestionService`` used for all lifecycle operations.
    """

    def __init__(self, service: IngestionService) -> None:
        self._service = service

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit(
        self,
        asset_data: dict[str, Any],
        *,
        source: str,
        tenant_id: str,
    ) -> CandidateAsset:
        """Ingest a single asset and apply confidence-based routing.

        The ``asset_data`` dict must contain at minimum:
        - ``name`` (str)
        - ``source_uri`` (str)
        - ``confidence`` (str matching a :class:`ConfidenceLevel` value)
        - ``asset_type`` (str)

        The ``tenant_id`` parameter overrides any ``tenant_id`` present in
        ``asset_data`` so the caller always controls tenancy.

        Args:
            asset_data: Raw asset payload.
            source: Identifies the upstream source system (stored in metadata).
            tenant_id: Tenant scope for the created record.

        Returns:
            The ``CandidateAsset`` after confidence routing is applied.
        """
        metadata: dict[str, Any] = dict(asset_data.get("metadata") or {})
        metadata["intake_source"] = source

        confidence_raw = str(asset_data.get("confidence", ConfidenceLevel.LOW))
        confidence = ConfidenceLevel(confidence_raw.lower())

        asset = self._service.ingest(
            name=str(asset_data["name"]),
            asset_type=str(asset_data.get("asset_type", "")),
            source_uri=str(asset_data.get("source_uri") or ""),
            tenant_id=tenant_id,
            confidence=confidence,
            metadata=metadata,
        )

        asset = self._apply_routing(asset, confidence)
        logger.info(
            "intake_submitted",
            asset_id=asset.id,
            confidence=confidence,
            status=asset.status,
            tenant_id=tenant_id,
        )
        return asset

    def batch_submit(
        self,
        assets: list[dict[str, Any]],
        *,
        source: str,
        tenant_id: str,
    ) -> list[CandidateAsset]:
        """Submit multiple assets as a batch.

        Failures for individual items are captured in the returned asset's
        metadata (``intake_error`` key) so that one bad entry does not abort
        the remainder of the batch.  Successfully processed assets are returned
        normally.

        Args:
            assets: List of raw asset payloads.
            source: Identifies the upstream source system.
            tenant_id: Tenant scope for all created records.

        Returns:
            A list of ``CandidateAsset`` objects, one per input item.
            Items that failed during processing carry ``intake_error`` in
            their metadata and are represented as CANDIDATE-status placeholder
            records.
        """
        results: list[CandidateAsset] = []
        for raw in assets:
            try:
                asset = self.submit(raw, source=source, tenant_id=tenant_id)
                results.append(asset)
            except Exception as exc:  # noqa: BLE001
                # Use a safe placeholder name so ingest() does not re-raise on
                # the min_length constraint when the original name was empty.
                safe_name = str(raw.get("name") or "<unknown>") or "<unknown>"
                error_asset = self._service.ingest(
                    name=safe_name,
                    asset_type=str(raw.get("asset_type") or ""),
                    source_uri=str(raw.get("source_uri") or "") or None,
                    tenant_id=tenant_id,
                    confidence=ConfidenceLevel.LOW,
                    metadata={
                        "intake_source": source,
                        "intake_error": str(exc),
                    },
                )
                results.append(error_asset)
                logger.warning(
                    "intake_batch_item_error",
                    error=str(exc),
                    tenant_id=tenant_id,
                )
        return results

    def get_pipeline_stats(self, tenant_id: str) -> dict[str, int]:
        """Return per-status asset counts for a given tenant.

        Args:
            tenant_id: Tenant scope to filter by.

        Returns:
            A dict mapping each :class:`CandidateStatus` value (string) to
            the count of assets in that status for *tenant_id*.
        """
        stats: dict[str, int] = {status.value: 0 for status in CandidateStatus}
        for status in CandidateStatus:
            for asset in self._service.list_by_status(status):
                if asset.tenant_id == tenant_id:
                    stats[status.value] += 1
        return stats

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_routing(self, asset: CandidateAsset, confidence: ConfidenceLevel) -> CandidateAsset:
        """Apply confidence-based routing rules to a freshly ingested asset."""
        if confidence == ConfidenceLevel.HIGH:
            return self._service.validate(asset.id, operator="intake_pipeline")

        metadata_updates: dict[str, Any] = {"review_required": True}
        if confidence == ConfidenceLevel.LOW:
            metadata_updates["quarantine"] = True

        return self._service.patch_metadata(asset.id, metadata_updates)
