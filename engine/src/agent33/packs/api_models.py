"""Pydantic models for pack API request/response payloads."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - Pydantic needs this at runtime

from pydantic import BaseModel, Field

from agent33.packs.provenance_models import (  # noqa: TC001
    PackProvenance,
    PackTrustPolicy,
    TrustLevel,
)


class PackSummary(BaseModel):
    """Compact pack representation for list endpoints."""

    name: str
    version: str
    description: str = ""
    author: str = ""
    tags: list[str] = Field(default_factory=list)
    category: str = ""
    skills_count: int = 0
    status: str = "installed"


class PackDetail(BaseModel):
    """Full pack details for get endpoints."""

    name: str
    version: str
    description: str = ""
    author: str = ""
    license: str = ""
    tags: list[str] = Field(default_factory=list)
    category: str = ""
    skills: list[PackSkillInfo] = Field(default_factory=list)
    loaded_skill_names: list[str] = Field(default_factory=list)
    engine_min_version: str = ""
    installed_at: datetime | None = None
    source: str = "local"
    source_reference: str = ""
    checksum: str = ""
    status: str = "installed"
    provenance: PackProvenance | None = None


class PackSkillInfo(BaseModel):
    """Skill info within a pack detail response."""

    name: str
    path: str = ""
    description: str = ""
    category: str = ""
    provenance: str = ""
    required: bool = True


# Fix forward reference
PackDetail.model_rebuild()


class InstallRequest(BaseModel):
    """Request body for pack installation."""

    source_type: str = Field(
        default="local",
        description="Source type: 'local'",
    )
    path: str = Field(
        default="",
        description="Local filesystem path to pack directory",
    )
    name: str = Field(
        default="",
        description="Pack name for marketplace lookup",
    )
    version: str = Field(
        default="",
        description="Target version (empty = latest)",
    )


class InstallResponse(BaseModel):
    """Response for install/upgrade operations."""

    success: bool
    pack_name: str
    version: str = ""
    skills_loaded: int = 0
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PackUpgradeRequest(BaseModel):
    """Request body for pack upgrades."""

    source_type: str = Field(
        default="marketplace",
        description="Source type: 'local' or 'marketplace'",
    )
    path: str = Field(default="", description="Local filesystem path to a pack directory")
    name: str = Field(default="", description="Marketplace pack name override")
    version: str = Field(default="", description="Target version (empty = latest)")


class PackRollbackResponse(BaseModel):
    """Response for rollback operations."""

    success: bool
    pack_name: str
    version: str = ""
    restored_from_version: str = ""
    errors: list[str] = Field(default_factory=list)


class EnableDisableResponse(BaseModel):
    """Response for enable/disable operations."""

    success: bool
    pack_name: str
    tenant_id: str
    action: str  # "enabled" or "disabled"


class SearchRequest(BaseModel):
    """Request parameters for pack search."""

    query: str = Field(..., min_length=1, description="Search query string")


class PackSearchResult(BaseModel):
    """Search result item."""

    name: str
    version: str
    description: str = ""
    author: str = ""
    tags: list[str] = Field(default_factory=list)
    match_score: float = 0.0


class MarketplacePackVersionInfo(BaseModel):
    """Marketplace version metadata."""

    version: str
    description: str = ""
    author: str = ""
    tags: list[str] = Field(default_factory=list)
    category: str = ""
    skills_count: int = 0
    source_name: str = ""
    source_type: str = "local"
    trust_level: TrustLevel | None = None


class MarketplacePackSummary(BaseModel):
    """Marketplace pack summary for listing/search."""

    name: str
    description: str = ""
    author: str = ""
    tags: list[str] = Field(default_factory=list)
    category: str = ""
    latest_version: str
    versions_count: int = 0
    sources: list[str] = Field(default_factory=list)
    trust_level: TrustLevel | None = None


class MarketplacePackDetail(BaseModel):
    """Marketplace pack detail with all available versions."""

    name: str
    description: str = ""
    author: str = ""
    tags: list[str] = Field(default_factory=list)
    category: str = ""
    latest_version: str
    versions: list[MarketplacePackVersionInfo] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class MarketplaceInstallRequest(BaseModel):
    """Request body for marketplace installs."""

    name: str = Field(..., min_length=1, description="Marketplace pack name")
    version: str = Field(default="", description="Target version (empty = latest)")


class TrustPolicyUpdateRequest(BaseModel):
    """Request body for trust-policy updates."""

    require_signature: bool | None = None
    min_trust_level: TrustLevel | None = None
    allowed_signers: list[str] | None = None


class TrustPolicyResponse(BaseModel):
    """Current pack trust policy."""

    policy: PackTrustPolicy


class PackTrustResponse(BaseModel):
    """Trust and provenance state for one installed pack."""

    pack_name: str
    installed_version: str = ""
    source: str = ""
    source_reference: str = ""
    provenance: PackProvenance | None = None
    policy: PackTrustPolicy
    allowed: bool
    reason: str = ""


class PackRecoveryDependent(BaseModel):
    """Installed pack that depends on the selected pack."""

    name: str
    version: str = ""
    version_constraint: str = ""
    status: str = "installed"


class PackRecoveryArchive(BaseModel):
    """Archived pack revision available for rollback."""

    version: str
    archived_at: datetime


class PackRecoveryPreviewResponse(BaseModel):
    """Beginner-safe preview for upgrade, uninstall, and rollback decisions."""

    pack_name: str
    installed_version: str
    target_version: str = ""
    affected_skills: list[str] = Field(default_factory=list)
    enabled_tenants: list[str] = Field(default_factory=list)
    dependents: list[PackRecoveryDependent] = Field(default_factory=list)
    compatibility_errors: list[str] = Field(default_factory=list)
    archived_versions: list[PackRecoveryArchive] = Field(default_factory=list)
    can_uninstall_safely: bool
    can_upgrade_safely: bool
    can_rollback: bool
    recommended_action: str
    warnings: list[str] = Field(default_factory=list)


class EnablementMatrixResponse(BaseModel):
    """Tenant enablement matrix for installed packs."""

    packs: list[str] = Field(default_factory=list)
    tenants: list[str] = Field(default_factory=list)
    matrix: dict[str, dict[str, bool]] = Field(default_factory=dict)


class EnablementMatrixUpdateRequest(BaseModel):
    """Bulk enablement updates for installed packs."""

    matrix: dict[str, dict[str, bool]] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Curation request/response models (Phase 33)
# ---------------------------------------------------------------------------


class CurationSubmitRequest(BaseModel):
    """Request body for submitting a pack for curation."""

    pack_name: str = Field(..., min_length=1, description="Name of the installed pack")
    version: str = Field(default="", description="Version to submit (empty = current)")


class CurationReviewRequest(BaseModel):
    """Request body for completing a curation review."""

    decision: str = Field(
        ...,
        min_length=1,
        description="Review decision: 'approved' or 'changes_requested'",
    )
    reviewer_id: str = Field(..., min_length=1, description="Reviewer identifier")
    notes: str = Field(default="", description="Optional review notes")


class DeprecateRequest(BaseModel):
    """Request body for deprecating a curated pack."""

    reason: str = Field(default="", description="Deprecation reason")


class CategoryCreateRequest(BaseModel):
    """Request body for creating a marketplace category."""

    slug: str = Field(..., min_length=1, max_length=64, description="Category slug")
    label: str = Field(..., min_length=1, max_length=128, description="Display label")
    description: str = Field(default="", description="Category description")
    parent_slug: str = Field(default="", description="Parent category slug (empty = top-level)")


class CategoryUpdateRequest(BaseModel):
    """Request body for updating a marketplace category."""

    label: str = Field(default="", description="Updated display label")
    description: str = Field(default="", description="Updated description")
    parent_slug: str = Field(default="", description="Updated parent slug")
