"""Trust analytics service for pack trust dashboard.

Provides aggregate trust metrics, trust chain inspection, audit trail
retrieval, and batch signature verification across all installed packs.
Integrates with PackRegistry, TrustPolicyManager, ProvenanceCollector,
and CurationService to produce a unified trust dashboard view.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from pydantic import BaseModel, Field

from agent33.packs.provenance import evaluate_trust, verify_pack
from agent33.packs.provenance_models import TrustLevel

if TYPE_CHECKING:
    from agent33.packs.curation_service import CurationService
    from agent33.packs.registry import PackRegistry
    from agent33.packs.trust_manager import TrustPolicyManager
    from agent33.provenance.collector import ProvenanceCollector

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class TrustOverview(BaseModel):
    """Aggregate trust metrics for all installed packs."""

    total_packs: int = 0
    signed_packs: int = 0
    unsigned_packs: int = 0
    by_trust_level: dict[str, int] = Field(default_factory=dict)
    signature_rate: float = 0.0
    policy_compliant: int = 0
    policy_violations: int = 0
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TrustChainEntry(BaseModel):
    """Trust and signature status for a single installed pack."""

    pack_name: str
    version: str
    trust_level: str
    signer_id: str | None = None
    signed_at: datetime | None = None
    signature_valid: bool | None = None
    policy_decision: str = "ALLOW"


class TrustAuditRecord(BaseModel):
    """A single trust-relevant audit event."""

    pack_name: str
    event_type: str
    timestamp: datetime
    details: dict[str, Any] = Field(default_factory=dict)


class TrustDashboardSummary(BaseModel):
    """Composite dashboard payload combining all trust analytics."""

    overview: TrustOverview
    trust_chain: list[TrustChainEntry]
    recent_audit: list[TrustAuditRecord]
    current_policy: dict[str, Any] = Field(default_factory=dict)
    curation_stats: dict[str, Any] | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class TrustAnalyticsService:
    """Compute trust analytics from installed packs and provenance state.

    Wires together pack registry, trust policy manager, provenance collector,
    and curation service to build aggregate dashboard views.
    """

    def __init__(
        self,
        pack_registry: PackRegistry,
        trust_manager: TrustPolicyManager,
        provenance_collector: ProvenanceCollector | None = None,
        curation_service: CurationService | None = None,
        *,
        verification_key: str = "",
    ) -> None:
        self._pack_registry = pack_registry
        self._trust_manager = trust_manager
        self._provenance_collector = provenance_collector
        self._curation_service = curation_service
        self._verification_key = verification_key

    # -- Overview ----------------------------------------------------------

    def get_overview(self) -> TrustOverview:
        """Scan all installed packs and compute aggregate trust metrics."""
        packs = self._pack_registry.list_installed()
        policy = self._trust_manager.get_policy()

        total = len(packs)
        signed = 0
        unsigned = 0
        by_trust_level: dict[str, int] = {}
        compliant = 0
        violations = 0

        for pack in packs:
            prov = pack.provenance
            if prov is not None:
                signed += 1
                level_key = prov.trust_level.value
            else:
                unsigned += 1
                level_key = TrustLevel.UNTRUSTED.value

            by_trust_level[level_key] = by_trust_level.get(level_key, 0) + 1

            decision = evaluate_trust(prov, policy)
            if decision.allowed:
                compliant += 1
            else:
                violations += 1

        signature_rate = (signed / total * 100.0) if total > 0 else 0.0

        return TrustOverview(
            total_packs=total,
            signed_packs=signed,
            unsigned_packs=unsigned,
            by_trust_level=by_trust_level,
            signature_rate=round(signature_rate, 2),
            policy_compliant=compliant,
            policy_violations=violations,
        )

    # -- Trust chain -------------------------------------------------------

    def get_trust_chain(self) -> list[TrustChainEntry]:
        """Build trust chain entries for every installed pack."""
        packs = self._pack_registry.list_installed()
        policy = self._trust_manager.get_policy()
        entries: list[TrustChainEntry] = []

        for pack in packs:
            prov = pack.provenance
            decision = evaluate_trust(prov, policy)

            if prov is not None:
                # Attempt signature verification if we have a key
                sig_valid: bool | None = None
                if self._verification_key:
                    try:
                        from agent33.packs.loader import load_pack_manifest

                        manifest = load_pack_manifest(pack.pack_dir)
                        sig_valid = verify_pack(manifest, prov, self._verification_key)
                    except Exception:
                        sig_valid = None

                entries.append(
                    TrustChainEntry(
                        pack_name=pack.name,
                        version=pack.version,
                        trust_level=prov.trust_level.value,
                        signer_id=prov.signer_id,
                        signed_at=prov.signed_at,
                        signature_valid=sig_valid,
                        policy_decision="ALLOW" if decision.allowed else "DENY",
                    )
                )
            else:
                entries.append(
                    TrustChainEntry(
                        pack_name=pack.name,
                        version=pack.version,
                        trust_level=TrustLevel.UNTRUSTED.value,
                        signer_id=None,
                        signed_at=None,
                        signature_valid=None,
                        policy_decision="ALLOW" if decision.allowed else "DENY",
                    )
                )

        return entries

    # -- Audit trail -------------------------------------------------------

    def get_audit_trail(self, limit: int = 50) -> list[TrustAuditRecord]:
        """Retrieve recent trust-related audit records from the provenance collector.

        Filters to PACK_INSTALL source events and converts them into
        TrustAuditRecord entries.  Returns an empty list if no provenance
        collector is available.
        """
        if self._provenance_collector is None:
            return []

        from agent33.provenance.models import ProvenanceSource

        receipts = self._provenance_collector.query(
            source=ProvenanceSource.PACK_INSTALL,
            limit=limit,
        )

        records: list[TrustAuditRecord] = []
        for receipt in receipts:
            pack_name = receipt.metadata.get("pack_name", "unknown")
            event_type = receipt.metadata.get("event_type", "install")
            records.append(
                TrustAuditRecord(
                    pack_name=pack_name,
                    event_type=event_type,
                    timestamp=receipt.timestamp,
                    details=dict(receipt.metadata),
                )
            )

        return records

    # -- Full dashboard ----------------------------------------------------

    def get_dashboard(self) -> TrustDashboardSummary:
        """Assemble the full trust dashboard: overview, chain, audit, policy, curation."""
        overview = self.get_overview()
        trust_chain = self.get_trust_chain()
        audit_trail = self.get_audit_trail()
        policy = self._trust_manager.get_policy()
        policy_dict = policy.model_dump(mode="json")

        curation_stats: dict[str, Any] | None = None
        if self._curation_service is not None:
            curation_stats = self._build_curation_stats()

        return TrustDashboardSummary(
            overview=overview,
            trust_chain=trust_chain,
            recent_audit=audit_trail,
            current_policy=policy_dict,
            curation_stats=curation_stats,
        )

    # -- Batch verification ------------------------------------------------

    def verify_all_signatures(self) -> list[dict[str, Any]]:
        """Batch-verify signatures for all signed packs.

        Returns a list of result dicts, one per signed pack, each containing:
          - pack_name: str
          - version: str
          - signer_id: str
          - valid: bool | None (None if verification_key not set)
          - error: str (non-empty if verification raised)
        """
        packs = self._pack_registry.list_installed()
        results: list[dict[str, Any]] = []

        for pack in packs:
            if pack.provenance is None:
                continue

            result: dict[str, Any] = {
                "pack_name": pack.name,
                "version": pack.version,
                "signer_id": pack.provenance.signer_id,
                "valid": None,
                "error": "",
            }

            if not self._verification_key:
                result["error"] = "no verification key configured"
                results.append(result)
                continue

            try:
                from agent33.packs.loader import load_pack_manifest

                manifest = load_pack_manifest(pack.pack_dir)
                result["valid"] = verify_pack(manifest, pack.provenance, self._verification_key)
            except Exception as exc:
                result["valid"] = None
                result["error"] = str(exc)

            results.append(result)

        return results

    # -- Internal helpers --------------------------------------------------

    def _build_curation_stats(self) -> dict[str, Any]:
        """Aggregate curation stats from the CurationService."""
        assert self._curation_service is not None  # noqa: S101

        from agent33.packs.curation import CurationStatus

        all_records = self._curation_service.list_curated()
        status_counts: dict[str, int] = {}
        for record in all_records:
            key = record.status.value
            status_counts[key] = status_counts.get(key, 0) + 1

        featured = self._curation_service.list_curated(featured_only=True)

        return {
            "total_records": len(all_records),
            "by_status": status_counts,
            "featured_count": len(featured),
            "statuses": [s.value for s in CurationStatus],
        }
