"""Read-only restore planning for platform backup archives."""

from __future__ import annotations

import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from agent33.backup.archive import MANIFEST_FILENAME, is_safe_archive_member
from agent33.backup.service import BackupService, _compute_checksum

if TYPE_CHECKING:
    from agent33.backup.manifest import BackupAsset


class RestoreAssetPlan(BaseModel):
    """Preview of the action for one backed-up asset."""

    relative_path: str
    asset_type: str
    action: str
    current_exists: bool
    size_bytes: int = 0


class RestoreConflict(BaseModel):
    """Conflict that would need operator review before restore execution."""

    relative_path: str
    conflict_type: str
    message: str
    resolution: str


class RestorePlan(BaseModel):
    """Read-only preview of a potential restore."""

    backup_id: str
    backup_version: str
    current_version: str
    assets_to_restore: list[RestoreAssetPlan] = Field(default_factory=list)
    conflicts: list[RestoreConflict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    estimated_duration: str = ""


class RestoreExecutionResult(BaseModel):
    """Result of a gated restore execution."""

    backup_id: str
    restored_assets: list[RestoreAssetPlan] = Field(default_factory=list)
    skipped_assets: list[RestoreAssetPlan] = Field(default_factory=list)
    conflicts: list[RestoreConflict] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    success: bool = False


class RestorePlanningError(RuntimeError):
    """Raised when a restore plan cannot be generated safely."""


class RestorePlanner:
    """Generate a restore plan from a verified backup archive."""

    def __init__(self, backup_service: BackupService) -> None:
        self._backup_service = backup_service

    async def plan(self, backup_id: str, archive_path: Path) -> RestorePlan:
        """Build a read-only restore plan for a backup."""
        verify_result = await self._backup_service.verify(archive_path)
        if not verify_result.valid:
            failed = [check.message for check in verify_result.checks if not check.passed]
            raise RestorePlanningError(
                "Backup verification failed before restore planning: " + "; ".join(failed)
            )

        manifest = self._backup_service.load_manifest(archive_path)
        conflicts: list[RestoreConflict] = []
        asset_plans: list[RestoreAssetPlan] = []
        actionable_bytes = 0

        if manifest.runtime_version != self._backup_service.runtime_version:
            conflicts.append(
                RestoreConflict(
                    relative_path="",
                    conflict_type="version_mismatch",
                    message=(
                        f"Backup runtime version {manifest.runtime_version} differs from "
                        f"current runtime version {self._backup_service.runtime_version}"
                    ),
                    resolution="review",
                )
            )

        for asset in manifest.assets:
            if not asset.included:
                continue
            plan, asset_conflicts = self._plan_asset(asset)
            asset_plans.append(plan)
            conflicts.extend(asset_conflicts)
            if plan.action != "skip":
                actionable_bytes += asset.size_bytes

        warnings = [
            "This endpoint generates a restore plan only; restore execution is a separate "
            "destructive workflow with additional safety gates.",
            "Create a fresh backup immediately before any future destructive restore attempt.",
            *verify_result.warnings,
        ]
        return RestorePlan(
            backup_id=backup_id,
            backup_version=manifest.runtime_version,
            current_version=self._backup_service.runtime_version,
            assets_to_restore=asset_plans,
            conflicts=conflicts,
            warnings=warnings,
            estimated_duration=_estimate_duration(actionable_bytes),
        )

    async def execute(
        self,
        backup_id: str,
        archive_path: Path,
        *,
        confirm: bool,
        allow_overwrite: bool = False,
    ) -> RestoreExecutionResult:
        """Execute a verified restore plan with destructive safety gates."""
        if not confirm:
            raise RestorePlanningError("Restore execution requires confirm=true")

        plan = await self.plan(backup_id, archive_path)
        blocking_conflicts = [
            conflict
            for conflict in plan.conflicts
            if conflict.resolution == "overwrite" and not allow_overwrite
        ]
        if blocking_conflicts:
            raise RestorePlanningError(
                "Restore conflicts require allow_overwrite=true: "
                + ", ".join(conflict.relative_path for conflict in blocking_conflicts)
            )

        manifest = self._backup_service.load_manifest(archive_path)
        asset_by_path = {asset.relative_path: asset for asset in manifest.assets if asset.included}
        restored: list[RestoreAssetPlan] = []
        skipped: list[RestoreAssetPlan] = []
        evidence = [
            f"backup_id:{backup_id}",
            "verification:passed",
            f"allow_overwrite:{str(allow_overwrite).lower()}",
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            staging_root = Path(tmp_dir)
            with tarfile.open(archive_path, "r:gz") as archive:
                archive_root = _archive_root(archive)
                for asset_plan in plan.assets_to_restore:
                    if asset_plan.action == "skip":
                        skipped.append(asset_plan)
                        continue
                    asset = asset_by_path.get(asset_plan.relative_path)
                    if asset is None:
                        skipped.append(asset_plan)
                        continue
                    target_path = self._backup_service.resolve_target_path(asset.relative_path)
                    if target_path is None:
                        skipped.append(asset_plan)
                        continue

                    staged_path = _stage_asset(
                        archive=archive,
                        archive_root=archive_root,
                        relative_path=asset.relative_path,
                        staging_root=staging_root,
                    )
                    _replace_target(staged_path, target_path, is_directory=asset.is_directory)
                    restored.append(asset_plan)
                    evidence.append(f"restored:{asset.relative_path}:{asset_plan.action}")

        return RestoreExecutionResult(
            backup_id=backup_id,
            restored_assets=restored,
            skipped_assets=skipped,
            conflicts=plan.conflicts,
            evidence=evidence,
            success=True,
        )

    def _plan_asset(self, asset: BackupAsset) -> tuple[RestoreAssetPlan, list[RestoreConflict]]:
        target_path = self._backup_service.resolve_target_path(asset.relative_path)
        if target_path is None:
            return (
                RestoreAssetPlan(
                    relative_path=asset.relative_path,
                    asset_type=asset.asset_type,
                    action="skip",
                    current_exists=False,
                    size_bytes=asset.size_bytes,
                ),
                [
                    RestoreConflict(
                        relative_path=asset.relative_path,
                        conflict_type="unmapped_asset",
                        message="No live target is mapped for this backup asset.",
                        resolution="skip",
                    )
                ],
            )

        current_exists = target_path.exists()
        if not current_exists:
            return (
                RestoreAssetPlan(
                    relative_path=asset.relative_path,
                    asset_type=asset.asset_type,
                    action="create",
                    current_exists=False,
                    size_bytes=asset.size_bytes,
                ),
                [],
            )

        conflicts: list[RestoreConflict] = []
        current_type_is_dir = target_path.is_dir()
        if current_type_is_dir != asset.is_directory:
            conflicts.append(
                RestoreConflict(
                    relative_path=asset.relative_path,
                    conflict_type="schema_change",
                    message="Current filesystem entry type differs from the backup asset type.",
                    resolution="overwrite",
                )
            )
            return (
                RestoreAssetPlan(
                    relative_path=asset.relative_path,
                    asset_type=asset.asset_type,
                    action="overwrite",
                    current_exists=True,
                    size_bytes=asset.size_bytes,
                ),
                conflicts,
            )

        try:
            current_checksum = _compute_checksum(target_path)
        except OSError as exc:
            raise RestorePlanningError(
                f"Failed to inspect current asset {asset.relative_path}: {exc}"
            ) from exc
        if current_checksum == asset.checksum:
            return (
                RestoreAssetPlan(
                    relative_path=asset.relative_path,
                    asset_type=asset.asset_type,
                    action="skip",
                    current_exists=True,
                    size_bytes=asset.size_bytes,
                ),
                [],
            )

        conflicts.append(
            RestoreConflict(
                relative_path=asset.relative_path,
                conflict_type="file_modified",
                message="Current asset contents differ from the backup snapshot.",
                resolution="overwrite",
            )
        )
        return (
            RestoreAssetPlan(
                relative_path=asset.relative_path,
                asset_type=asset.asset_type,
                action="overwrite",
                current_exists=True,
                size_bytes=asset.size_bytes,
            ),
            conflicts,
        )


def _estimate_duration(total_bytes: int) -> str:
    """Return a coarse restore duration estimate."""
    if total_bytes <= 0:
        return "No restore actions needed"
    if total_bytes < 1_000_000:
        return "Under 1 minute"
    if total_bytes < 100_000_000:
        return "1-2 minutes"
    return "Several minutes"


def _archive_root(archive: tarfile.TarFile) -> str:
    roots = {PurePosixPath(member.name).parts[0] for member in archive.getmembers() if member.name}
    if len(roots) != 1:
        raise RestorePlanningError("Archive must contain exactly one top-level root")
    return next(iter(roots))


def _stage_asset(
    *,
    archive: tarfile.TarFile,
    archive_root: str,
    relative_path: str,
    staging_root: Path,
) -> Path:
    source_prefix = PurePosixPath(archive_root) / relative_path
    staged_asset = staging_root / relative_path
    matched = False
    for member in archive.getmembers():
        if not is_safe_archive_member(member.name):
            raise RestorePlanningError(f"Unsafe archive member path: {member.name}")
        normalized = PurePosixPath(member.name)
        if normalized == PurePosixPath(archive_root) / MANIFEST_FILENAME:
            continue
        if normalized != source_prefix and source_prefix not in normalized.parents:
            continue
        matched = True
        relative_member = normalized.relative_to(source_prefix)
        destination = staged_asset / relative_member
        if member.isdir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        if not member.isfile():
            continue
        payload = archive.extractfile(member)
        if payload is None:
            raise RestorePlanningError(f"Could not read archive member: {member.name}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as handle:
            shutil.copyfileobj(payload, handle)
    if not matched:
        raise RestorePlanningError(f"Archive asset missing: {relative_path}")
    return staged_asset


def _replace_target(staged_path: Path, target_path: Path, *, is_directory: bool) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
        if target_path.is_dir():
            shutil.rmtree(target_path)
        else:
            target_path.unlink()
    if is_directory:
        shutil.copytree(staged_path, target_path)
    else:
        shutil.copy2(staged_path, target_path)
