"""Manifest and API models for platform backups."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class BackupMode(StrEnum):
    """Supported backup modes."""

    FULL = "full"
    CONFIG_ONLY = "config-only"
    NO_WORKSPACE = "no-workspace"


class BackupAsset(BaseModel):
    """A single asset considered for backup."""

    relative_path: str
    asset_type: str
    size_bytes: int = 0
    checksum: str = ""
    included: bool = True
    exclusion_reason: str = ""
    is_directory: bool = False
    source_path: str = Field(default="", exclude=True)


class BackupManifest(BaseModel):
    """Versioned manifest describing a backup archive."""

    schema_version: str = "1.0"
    backup_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    platform: str
    runtime_version: str
    archive_root: str
    backup_mode: BackupMode
    assets: list[BackupAsset] = Field(default_factory=list)
    checksums: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BackupProvenance(BaseModel):
    """Records who created the backup and from what state."""

    creator: str = ""
    source_roots: list[str] = Field(default_factory=list)
    runtime_version: str = ""
    platform: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class VerifyCheck(BaseModel):
    """A single archive verification check."""

    name: str
    passed: bool
    message: str = ""


class VerifyResult(BaseModel):
    """Archive verification outcome."""

    valid: bool
    checks: list[VerifyCheck] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class BackupSummary(BaseModel):
    """Lightweight backup summary for list responses."""

    backup_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    archive_path: str = ""
    mode: BackupMode = BackupMode.FULL
    label: str = ""
    size_bytes: int = 0
    asset_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class BackupListResponse(BaseModel):
    """Response for listing backup archives."""

    backups: list[BackupSummary] = Field(default_factory=list)
    count: int = 0
    note: str = ""


class BackupDetailResponse(BaseModel):
    """Response containing a backup summary and full manifest."""

    backup: BackupSummary
    manifest: BackupManifest


class BackupInventoryResponse(BaseModel):
    """Preview of the assets that would be included in a backup."""

    mode: BackupMode
    assets: list[BackupAsset] = Field(default_factory=list)
    count: int = 0
    warnings: list[str] = Field(default_factory=list)


class BackupResult(BaseModel):
    """Archive creation result."""

    success: bool
    backup_id: str
    archive_path: str = ""
    manifest: BackupManifest | None = None
    size_bytes: int = 0
    asset_count: int = 0
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    provenance: BackupProvenance | None = None
