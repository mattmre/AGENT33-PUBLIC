"""Data models for release automation, sync, and rollback."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class ReleaseType(StrEnum):
    """Release cadence type."""

    PATCH = "patch"
    MINOR = "minor"
    MAJOR = "major"


class ReleaseStatus(StrEnum):
    """Release lifecycle status."""

    PLANNED = "planned"
    FROZEN = "frozen"
    RC = "rc"
    VALIDATING = "validating"
    RELEASED = "released"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class CheckStatus(StrEnum):
    """Status of a release checklist item."""

    PENDING = "pending"
    PASS = "pass"
    FAIL = "fail"
    SKIPPED = "skipped"
    NA = "na"


class SyncStrategy(StrEnum):
    """How files are synced to downstream repos."""

    COPY = "copy"
    TEMPLATE = "template"
    REFERENCE = "reference"


class SyncFrequency(StrEnum):
    """When sync runs."""

    ON_RELEASE = "on_release"
    ON_CHANGE = "on_change"
    MANUAL = "manual"


class SyncStatus(StrEnum):
    """Status of a sync execution."""

    PENDING = "pending"
    DRY_RUN = "dry_run"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RollbackType(StrEnum):
    """Type of rollback."""

    IMMEDIATE = "immediate"
    PLANNED = "planned"
    PARTIAL = "partial"
    CONFIG = "config"


class RollbackStatus(StrEnum):
    """Status of a rollback."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Release checklist
# ---------------------------------------------------------------------------


class ReleaseCheck(BaseModel):
    """A single release checklist item (RL-01..RL-08)."""

    check_id: str
    name: str
    status: CheckStatus = CheckStatus.PENDING
    message: str = ""
    required: bool = True


# ---------------------------------------------------------------------------
# Release evidence
# ---------------------------------------------------------------------------


class ReleaseEvidence(BaseModel):
    """Evidence collected during a release."""

    gate_passed: bool = False
    success_rate: float = 0.0
    rework_rate: float = 0.0
    all_tasks_passed: bool = False
    checklist: list[ReleaseCheck] = Field(default_factory=list)
    commit_hash: str = ""
    branch: str = ""
    build_id: str = ""
    changelog_ref: str = ""
    release_notes_ref: str = ""


# ---------------------------------------------------------------------------
# Release
# ---------------------------------------------------------------------------


class Release(BaseModel):
    """A release record tracking the full lifecycle."""

    release_id: str = Field(default_factory=lambda: _new_id("REL"))
    version: str
    release_type: ReleaseType = ReleaseType.MINOR
    status: ReleaseStatus = ReleaseStatus.PLANNED

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    released_at: datetime | None = None
    released_by: str = ""

    evidence: ReleaseEvidence = Field(default_factory=ReleaseEvidence)

    # Metadata
    description: str = ""
    rc_version: str = ""
    tenant_id: str | None = None


# ---------------------------------------------------------------------------
# Sync models
# ---------------------------------------------------------------------------


class SyncTransform(BaseModel):
    """A transform applied during sync."""

    name: str
    config: dict[str, str] = Field(default_factory=dict)


class SyncRule(BaseModel):
    """A sync rule defining what to sync and where."""

    rule_id: str = Field(default_factory=lambda: _new_id("SYN"))
    source_pattern: str = "core/**/*.md"
    target_repo: str = ""
    target_path: str = ""
    strategy: SyncStrategy = SyncStrategy.COPY
    frequency: SyncFrequency = SyncFrequency.ON_RELEASE
    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    transforms: list[SyncTransform] = Field(default_factory=list)
    validate_checksum: bool = True
    validate_schema: bool = True


class SyncFileResult(BaseModel):
    """Result for a single file in a sync execution."""

    source_path: str
    target_path: str
    action: str = ""  # "added", "modified", "removed", "unchanged"
    checksum_valid: bool = True
    source_checksum: str = ""
    target_checksum: str = ""


class SyncExecution(BaseModel):
    """A single sync execution."""

    execution_id: str = Field(default_factory=lambda: _new_id("SXE"))
    rule_id: str = ""
    release_version: str = ""
    status: SyncStatus = SyncStatus.PENDING
    dry_run: bool = True
    io_mode: str = "dry_run"
    approved_dry_run_execution_id: str = ""
    source_root: str = ""
    target_root: str = ""

    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    files_added: int = 0
    files_modified: int = 0
    files_removed: int = 0
    file_results: list[SyncFileResult] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


class RollbackRecord(BaseModel):
    """Record of a rollback."""

    rollback_id: str = Field(default_factory=lambda: _new_id("RBK"))
    release_id: str = ""
    rollback_type: RollbackType = RollbackType.PLANNED
    status: RollbackStatus = RollbackStatus.PENDING

    reason: str = ""
    initiated_by: str = ""
    approved_by: str = ""

    target_version: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    steps_completed: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
