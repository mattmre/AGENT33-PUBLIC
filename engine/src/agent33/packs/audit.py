"""Pack audit service: health monitoring, audit log browsing, and compliance checks.

Provides operators with aggregate pack health metrics, per-pack health details,
a bounded in-memory audit event log, and compliance verification against
configurable rules. Integrates with PackRegistry, TrustAnalyticsService,
CurationService, and ProvenanceCollector.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import structlog
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agent33.packs.curation_service import CurationService
    from agent33.packs.registry import PackRegistry
    from agent33.packs.trust_analytics import TrustAnalyticsService
    from agent33.provenance.collector import ProvenanceCollector

logger = structlog.get_logger()

# Maximum number of audit events retained in the in-memory ring buffer.
_MAX_EVENTS = 500


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PackHealthStatus(StrEnum):
    """Health classification for a pack."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class PackHealthCheck(BaseModel):
    """Health check result for a single installed pack."""

    pack_name: str
    version: str
    health: PackHealthStatus
    issues: list[str] = Field(default_factory=list)
    skill_count: int = 0
    loaded_skills: int = 0
    missing_skills: list[str] = Field(default_factory=list)
    has_provenance: bool = False
    trust_level: str = "untrusted"
    quality_score: float | None = None
    curation_status: str | None = None
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PackHealthSummary(BaseModel):
    """Aggregate health metrics across all installed packs."""

    total_packs: int = 0
    healthy: int = 0
    degraded: int = 0
    unhealthy: int = 0
    unknown: int = 0
    health_rate: float = 0.0
    top_issues: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PackAuditEvent(BaseModel):
    """A recorded audit event for pack lifecycle changes."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    pack_name: str
    event_type: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    actor: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    previous_version: str | None = None
    new_version: str | None = None


class PackComplianceReport(BaseModel):
    """Compliance verification report for a single pack."""

    pack_name: str
    compliant: bool = True
    checks: list[dict[str, Any]] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class PackAuditService:
    """Audit, health monitoring, and compliance checking for installed packs.

    Wires together the pack registry, trust analytics, curation service,
    and provenance collector to produce health dashboards, audit trails,
    and compliance reports.
    """

    def __init__(
        self,
        pack_registry: PackRegistry,
        trust_analytics: TrustAnalyticsService | None = None,
        curation_service: CurationService | None = None,
        provenance_collector: ProvenanceCollector | None = None,
    ) -> None:
        self._pack_registry = pack_registry
        self._trust_analytics = trust_analytics
        self._curation_service = curation_service
        self._provenance_collector = provenance_collector
        self._events: list[PackAuditEvent] = []

    # -- Health checks -----------------------------------------------------

    def check_pack_health(self, pack_name: str) -> PackHealthCheck:
        """Check the health of a single installed pack.

        Evaluates:
        - Whether all declared skills are loaded
        - Whether provenance metadata exists
        - Quality score (from curation, if available)
        - Pack status (error state = unhealthy)

        Returns:
            PackHealthCheck with issues list and health classification.

        Raises:
            ValueError: If the pack is not installed.
        """
        pack = self._pack_registry.get(pack_name)
        if pack is None:
            raise ValueError(f"Pack '{pack_name}' is not installed")

        issues: list[str] = []

        # Skill loading check
        declared_skill_names = [s.name for s in pack.skills]
        loaded_qualified = set(pack.loaded_skill_names)
        missing: list[str] = []
        for skill_entry in pack.skills:
            qualified = f"{pack.name}/{skill_entry.name}"
            if qualified not in loaded_qualified:
                missing.append(skill_entry.name)

        if missing:
            issues.append(f"Missing skills: {', '.join(missing)}")

        # Provenance check
        has_provenance = pack.provenance is not None
        trust_level = "untrusted"
        if pack.provenance is not None:
            trust_level = pack.provenance.trust_level.value
        else:
            issues.append("No provenance signature")

        # Quality/curation check
        quality_score: float | None = None
        curation_status: str | None = None
        if self._curation_service is not None:
            record = self._curation_service.get_curation(pack_name)
            if record is not None:
                curation_status = record.status.value
                if record.quality is not None:
                    quality_score = record.quality.overall_score
                    if record.quality.overall_score < 0.5:
                        issues.append(f"Low quality score: {record.quality.overall_score:.2f}")

        # Pack status check
        from agent33.packs.models import PackStatus

        if pack.status == PackStatus.ERROR:
            issues.append("Pack is in ERROR state")
        elif pack.status == PackStatus.DISABLED:
            issues.append("Pack is disabled")

        # Determine health classification
        health = self._classify_health(issues, pack)

        return PackHealthCheck(
            pack_name=pack.name,
            version=pack.version,
            health=health,
            issues=issues,
            skill_count=len(declared_skill_names),
            loaded_skills=len(pack.loaded_skill_names),
            missing_skills=missing,
            has_provenance=has_provenance,
            trust_level=trust_level,
            quality_score=quality_score,
            curation_status=curation_status,
        )

    def _classify_health(
        self,
        issues: list[str],
        pack: Any,
    ) -> PackHealthStatus:
        """Classify pack health based on collected issues."""
        from agent33.packs.models import PackStatus

        if pack.status == PackStatus.ERROR:
            return PackHealthStatus.UNHEALTHY

        # Missing skills makes it degraded, not unhealthy (pack is still usable)
        has_missing_skills = any("Missing skills" in i for i in issues)
        has_low_quality = any("Low quality" in i for i in issues)

        if has_missing_skills:
            return PackHealthStatus.DEGRADED

        # Multiple issues (e.g. no provenance + low quality) = degraded
        if len(issues) >= 2 and has_low_quality:
            return PackHealthStatus.DEGRADED

        # No significant issues
        if not issues or all("No provenance" in i or "disabled" in i.lower() for i in issues):
            # No provenance alone does not make it degraded; disabled is informational
            if any("disabled" in i.lower() for i in issues):
                return PackHealthStatus.DEGRADED
            return PackHealthStatus.HEALTHY

        return PackHealthStatus.HEALTHY

    def check_all_health(self) -> PackHealthSummary:
        """Compute aggregate health summary across all installed packs."""
        details = self.get_health_details()
        total = len(details)

        counts: dict[PackHealthStatus, int] = {
            PackHealthStatus.HEALTHY: 0,
            PackHealthStatus.DEGRADED: 0,
            PackHealthStatus.UNHEALTHY: 0,
            PackHealthStatus.UNKNOWN: 0,
        }
        all_issues: list[str] = []

        for check in details:
            counts[check.health] = counts.get(check.health, 0) + 1
            all_issues.extend(check.issues)

        # Top issues: most common issue strings
        issue_counts = Counter(all_issues)
        top_issues = [issue for issue, _ in issue_counts.most_common(5)]

        health_rate = (counts[PackHealthStatus.HEALTHY] / total * 100.0) if total > 0 else 0.0

        return PackHealthSummary(
            total_packs=total,
            healthy=counts[PackHealthStatus.HEALTHY],
            degraded=counts[PackHealthStatus.DEGRADED],
            unhealthy=counts[PackHealthStatus.UNHEALTHY],
            unknown=counts[PackHealthStatus.UNKNOWN],
            health_rate=round(health_rate, 2),
            top_issues=top_issues,
        )

    def get_health_details(self) -> list[PackHealthCheck]:
        """Return per-pack health check results for all installed packs."""
        packs = self._pack_registry.list_installed()
        results: list[PackHealthCheck] = []
        for pack in packs:
            try:
                check = self.check_pack_health(pack.name)
                results.append(check)
            except Exception:
                logger.warning(
                    "pack_health_check_failed",
                    pack_name=pack.name,
                    exc_info=True,
                )
                results.append(
                    PackHealthCheck(
                        pack_name=pack.name,
                        version=pack.version,
                        health=PackHealthStatus.UNKNOWN,
                        issues=["Health check failed with exception"],
                    )
                )
        return results

    # -- Audit log ---------------------------------------------------------

    def record_event(
        self,
        pack_name: str,
        event_type: str,
        actor: str = "",
        details: dict[str, Any] | None = None,
        previous_version: str | None = None,
        new_version: str | None = None,
    ) -> PackAuditEvent:
        """Record an audit event in the in-memory ring buffer.

        The buffer is bounded to ``_MAX_EVENTS`` entries; oldest events
        are evicted when the limit is reached.
        """
        event = PackAuditEvent(
            pack_name=pack_name,
            event_type=event_type,
            actor=actor,
            details=details or {},
            previous_version=previous_version,
            new_version=new_version,
        )
        self._events.append(event)

        # Trim to max size
        if len(self._events) > _MAX_EVENTS:
            self._events = self._events[-_MAX_EVENTS:]

        logger.info(
            "pack_audit_event_recorded",
            pack_name=pack_name,
            event_type=event_type,
            actor=actor,
        )
        return event

    def get_audit_log(
        self,
        pack_name: str | None = None,
        event_type: str | None = None,
        limit: int = 50,
    ) -> list[PackAuditEvent]:
        """Retrieve audit events with optional filters.

        Args:
            pack_name: Filter to events for a specific pack.
            event_type: Filter to a specific event type.
            limit: Maximum number of events to return (most recent first).

        Returns:
            List of matching events sorted newest-first.
        """
        filtered = self._events
        if pack_name is not None:
            filtered = [e for e in filtered if e.pack_name == pack_name]
        if event_type is not None:
            filtered = [e for e in filtered if e.event_type == event_type]

        # Return newest first, limited
        return list(reversed(filtered))[:limit]

    # -- Compliance checks -------------------------------------------------

    def compliance_check(self, pack_name: str) -> PackComplianceReport:
        """Check a pack against compliance rules.

        Compliance checks:
        1. Has valid manifest (pack exists and is installed)
        2. Has provenance signature
        3. Passes minimum quality threshold (score >= 0.5)
        4. Has non-empty license
        5. No skill name conflicts with other packs

        Args:
            pack_name: Name of the pack to check.

        Returns:
            PackComplianceReport with individual check results.

        Raises:
            ValueError: If the pack is not installed.
        """
        pack = self._pack_registry.get(pack_name)
        if pack is None:
            raise ValueError(f"Pack '{pack_name}' is not installed")

        checks: list[dict[str, Any]] = []
        all_passed = True

        # 1. Valid manifest (pack is installed and has a name/version)
        has_manifest = bool(pack.name and pack.version)
        checks.append(
            {
                "name": "valid_manifest",
                "passed": has_manifest,
                "reason": (
                    "Pack has valid name and version"
                    if has_manifest
                    else "Missing name or version"
                ),
            }
        )
        if not has_manifest:
            all_passed = False

        # 2. Has provenance signature
        has_provenance = pack.provenance is not None
        checks.append(
            {
                "name": "has_provenance",
                "passed": has_provenance,
                "reason": (
                    f"Signed by {pack.provenance.signer_id}"
                    if has_provenance and pack.provenance is not None
                    else "No provenance signature"
                ),
            }
        )
        if not has_provenance:
            all_passed = False

        # 3. Minimum quality threshold
        quality_passed = True
        quality_reason = "No curation data available (assumed passing)"
        if self._curation_service is not None:
            record = self._curation_service.get_curation(pack_name)
            if record is not None and record.quality is not None:
                quality_passed = record.quality.overall_score >= 0.5
                quality_reason = f"Quality score: {record.quality.overall_score:.2f}" + (
                    " (below 0.5 threshold)" if not quality_passed else " (passes threshold)"
                )
        checks.append(
            {
                "name": "quality_threshold",
                "passed": quality_passed,
                "reason": quality_reason,
            }
        )
        if not quality_passed:
            all_passed = False

        # 4. Non-empty license
        has_license = bool(pack.license.strip()) if pack.license else False
        checks.append(
            {
                "name": "has_license",
                "passed": has_license,
                "reason": f"License: {pack.license}" if has_license else "No license specified",
            }
        )
        if not has_license:
            all_passed = False

        # 5. No skill name conflicts with other installed packs
        conflict_found = False
        conflict_reason = "No skill name conflicts"
        other_packs = self._pack_registry.list_installed()
        pack_skill_names = {s.name for s in pack.skills}
        for other in other_packs:
            if other.name == pack_name:
                continue
            other_skill_names = {s.name for s in other.skills}
            overlapping = pack_skill_names & other_skill_names
            if overlapping:
                conflict_found = True
                conflict_reason = (
                    f"Skill name conflict with '{other.name}': {', '.join(sorted(overlapping))}"
                )
                break

        checks.append(
            {
                "name": "no_skill_conflicts",
                "passed": not conflict_found,
                "reason": conflict_reason,
            }
        )
        if conflict_found:
            all_passed = False

        return PackComplianceReport(
            pack_name=pack_name,
            compliant=all_passed,
            checks=checks,
        )
