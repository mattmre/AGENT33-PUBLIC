"""Skill Packs: versioned, distributable bundles of related skills.

Packs are an organizational layer above individual skills. They provide
grouping, versioned dependency resolution, tenant-scoped enablement,
and external format compatibility (SkillsBench, MCP tools).

Existing standalone skills continue to work unchanged.
"""

from __future__ import annotations

from agent33.packs.audit import (
    PackAuditEvent,
    PackAuditService,
    PackComplianceReport,
    PackHealthCheck,
    PackHealthStatus,
    PackHealthSummary,
)
from agent33.packs.categories import CategoryRegistry, MarketplaceCategory
from agent33.packs.conflicts import (
    ConflictKind,
    Resolution,
    ResolutionAction,
    VersionConflict,
    detect_conflicts,
    resolve_conflicts,
)
from agent33.packs.curation import (
    CurationRecord,
    CurationStateMachine,
    CurationStatus,
    InvalidCurationTransitionError,
    QualityAssessment,
    QualityCheck,
    assess_pack_quality,
)
from agent33.packs.curation_service import CurationService
from agent33.packs.hub import PackHub, PackHubConfig, PackHubEntry
from agent33.packs.manifest import PackManifest
from agent33.packs.marketplace import (
    LocalPackMarketplace,
    MarketplacePackRecord,
    MarketplacePackVersion,
)
from agent33.packs.models import (
    InstalledPack,
    InstallResult,
    OutcomePackEntry,
    PackDependency,
    PackGovernance,
    PackSkillEntry,
    PackSource,
    PackStatus,
)
from agent33.packs.outcome_pack import (
    OutcomePackManifest,
    outcome_pack_to_dict,
    parse_outcome_pack_yaml,
)
from agent33.packs.provenance import (
    evaluate_trust,
    sign_pack,
    verify_pack,
)
from agent33.packs.provenance_models import (
    PackProvenance,
    PackTrustPolicy,
    TrustDecision,
    TrustLevel,
)
from agent33.packs.readiness import (
    OutcomePackReadinessContext,
    OutcomePackReadinessEvaluator,
    OutcomePackReadinessResult,
    OutcomePackReadinessState,
    OutcomePackRequirementReadiness,
    OutcomePackRequirementState,
)
from agent33.packs.sharing import PackShareRequest, PackSharingService

__all__ = [
    "CategoryRegistry",
    "PackHub",
    "PackHubConfig",
    "PackHubEntry",
    "PackShareRequest",
    "PackSharingService",
    "PackAuditEvent",
    "PackAuditService",
    "PackComplianceReport",
    "PackHealthCheck",
    "PackHealthStatus",
    "PackHealthSummary",
    "ConflictKind",
    "CurationRecord",
    "CurationService",
    "CurationStateMachine",
    "CurationStatus",
    "InstalledPack",
    "InstallResult",
    "InvalidCurationTransitionError",
    "LocalPackMarketplace",
    "MarketplaceCategory",
    "MarketplacePackRecord",
    "MarketplacePackVersion",
    "OutcomePackEntry",
    "OutcomePackManifest",
    "OutcomePackReadinessContext",
    "OutcomePackReadinessEvaluator",
    "OutcomePackReadinessResult",
    "OutcomePackReadinessState",
    "OutcomePackRequirementReadiness",
    "OutcomePackRequirementState",
    "PackDependency",
    "PackGovernance",
    "PackManifest",
    "PackProvenance",
    "PackSkillEntry",
    "PackSource",
    "PackStatus",
    "PackTrustPolicy",
    "QualityAssessment",
    "QualityCheck",
    "Resolution",
    "ResolutionAction",
    "TrustDecision",
    "TrustLevel",
    "VersionConflict",
    "assess_pack_quality",
    "detect_conflicts",
    "evaluate_trust",
    "outcome_pack_to_dict",
    "parse_outcome_pack_yaml",
    "resolve_conflicts",
    "sign_pack",
    "verify_pack",
]
