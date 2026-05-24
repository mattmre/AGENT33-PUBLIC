"""Platform backup inventory, archive creation, and verification."""

from __future__ import annotations

import hashlib
import json
import platform
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from uuid import uuid4

from agent33.backup.archive import MANIFEST_FILENAME, build_archive_stem, is_safe_archive_member
from agent33.backup.manifest import (
    BackupAsset,
    BackupDetailResponse,
    BackupInventoryResponse,
    BackupListResponse,
    BackupManifest,
    BackupMode,
    BackupProvenance,
    BackupResult,
    BackupSummary,
    VerifyCheck,
    VerifyResult,
)
from agent33.state_paths import RuntimeStatePaths

if TYPE_CHECKING:
    from agent33.config import Settings

SUPPORTED_SCHEMA_VERSIONS = frozenset({"1.0"})


class BackupError(RuntimeError):
    """Raised when backup creation or validation fails."""


@dataclass(frozen=True)
class _AssetCandidate:
    relative_path: str
    asset_type: str
    source_path: Path | None
    included_modes: frozenset[BackupMode]
    missing_reason: str = "Asset source not found"


class BackupService:
    """Creates and verifies platform-level backups."""

    def __init__(
        self,
        *,
        backup_dir: Path,
        settings: Settings,
        app_root: Path,
        workspace_dir: Path | None = None,
        state_paths: RuntimeStatePaths | None = None,
    ) -> None:
        self._state_paths = state_paths or RuntimeStatePaths.from_app_root(app_root)
        self._backup_dir = self._state_paths.ensure_approved(backup_dir)
        self._settings = settings
        self._app_root = app_root.resolve()
        self._workspace_dir = workspace_dir
        self._backup_dir.mkdir(parents=True, exist_ok=True)

    @property
    def runtime_version(self) -> str:
        """Return the current engine runtime version used in backup metadata."""
        return "0.1.0"

    def inventory(self, *, mode: BackupMode = BackupMode.FULL) -> BackupInventoryResponse:
        """Preview the assets that would be included in a backup."""
        normalized_mode = BackupMode(mode)
        warnings: list[str] = []
        assets: list[BackupAsset] = []

        for candidate in self._asset_candidates():
            asset = self._materialize_asset(candidate, normalized_mode)
            if asset.exclusion_reason:
                warnings.append(f"{asset.relative_path}: {asset.exclusion_reason}")
            assets.append(asset)

        return BackupInventoryResponse(
            mode=normalized_mode,
            assets=assets,
            count=len(assets),
            warnings=warnings,
        )

    async def create(
        self,
        *,
        mode: BackupMode = BackupMode.FULL,
        label: str = "",
        creator: str = "",
    ) -> BackupResult:
        """Create a new platform backup archive and verify it."""
        normalized_mode = BackupMode(mode)
        inventory = self.inventory(mode=normalized_mode)
        created_at = BackupProvenance().created_at
        short_id = uuid4().hex[:6]
        backup_id = f"{created_at.strftime('%Y%m%d-%H%M%S')}-{short_id}"
        archive_stem = build_archive_stem(created_at, normalized_mode.value, short_id)
        manifest = BackupManifest(
            backup_id=backup_id,
            created_at=created_at,
            platform=platform.system().lower(),
            runtime_version=self.runtime_version,
            archive_root=str(self._app_root.resolve()),
            backup_mode=normalized_mode,
            assets=inventory.assets,
            checksums={
                asset.relative_path: asset.checksum
                for asset in inventory.assets
                if asset.included and asset.checksum
            },
            metadata={"label": label},
        )
        archive_path = self._backup_dir / f"{archive_stem}.tar.gz"

        with tempfile.TemporaryDirectory(dir=str(self._backup_dir)) as tmp_dir:
            staging_root = Path(tmp_dir) / archive_stem
            staging_root.mkdir(parents=True, exist_ok=True)
            for asset in inventory.assets:
                if not asset.included:
                    continue
                source = Path(asset.source_path)
                target = staging_root / PurePosixPath(asset.relative_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.is_dir():
                    shutil.copytree(source, target)
                else:
                    shutil.copy2(source, target)

            (staging_root / MANIFEST_FILENAME).write_text(
                json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            from agent33.backup.archive import write_tar_gz

            write_tar_gz(staging_root, archive_path)

        verify_result = await self.verify(archive_path)
        errors = [check.message for check in verify_result.checks if not check.passed]
        return BackupResult(
            success=verify_result.valid,
            backup_id=backup_id,
            archive_path=str(archive_path),
            manifest=manifest,
            size_bytes=archive_path.stat().st_size if archive_path.exists() else 0,
            asset_count=sum(1 for asset in inventory.assets if asset.included),
            errors=errors,
            warnings=inventory.warnings + verify_result.warnings,
            provenance=BackupProvenance(
                creator=creator or label,
                source_roots=[
                    str(self._app_root.resolve()),
                    *([str(self._workspace_dir.resolve())] if self._workspace_dir else []),
                ],
                runtime_version=manifest.runtime_version,
                platform=manifest.platform,
                created_at=created_at,
            ),
        )

    async def verify(self, archive_path: Path) -> VerifyResult:
        """Verify a backup archive."""
        checks: list[VerifyCheck] = []
        warnings: list[str] = []

        if not archive_path.exists():
            return VerifyResult(
                valid=False,
                checks=[
                    VerifyCheck(
                        name="archive_exists",
                        passed=False,
                        message="Archive not found",
                    )
                ],
                warnings=[],
            )

        try:
            with tarfile.open(archive_path, "r:gz") as archive:
                members = archive.getmembers()
                checks.append(
                    VerifyCheck(
                        name="archive_readable",
                        passed=True,
                        message="Archive is readable",
                    )
                )
                safe_paths = all(is_safe_archive_member(member.name) for member in members)
                checks.append(
                    VerifyCheck(
                        name="archive_member_paths",
                        passed=safe_paths,
                        message=(
                            "Archive members are contained"
                            if safe_paths
                            else "Archive contains unsafe member paths"
                        ),
                    )
                )
                if not safe_paths:
                    return VerifyResult(valid=False, checks=checks, warnings=warnings)

                top_levels = {
                    PurePosixPath(member.name).parts[0] for member in members if member.name
                }
                single_root = len(top_levels) == 1
                checks.append(
                    VerifyCheck(
                        name="single_archive_root",
                        passed=single_root,
                        message=(
                            "Archive uses a single top-level root"
                            if single_root
                            else "Archive contains multiple top-level roots"
                        ),
                    )
                )
                if not single_root:
                    return VerifyResult(valid=False, checks=checks, warnings=warnings)

                archive_root = next(iter(top_levels))
                normalized_members = [
                    _strip_archive_root(member.name, archive_root) for member in members
                ]
                duplicates = _find_duplicates([name for name in normalized_members if name])
                checks.append(
                    VerifyCheck(
                        name="duplicate_members",
                        passed=not duplicates,
                        message=(
                            "No duplicate normalized entries"
                            if not duplicates
                            else f"Duplicate entries detected: {', '.join(duplicates)}"
                        ),
                    )
                )

                manifest_member = archive.getmember(f"{archive_root}/{MANIFEST_FILENAME}")
                manifest_payload = archive.extractfile(manifest_member)
                if manifest_payload is None:
                    raise BackupError("Manifest payload is missing")
                manifest = BackupManifest.model_validate(
                    json.loads(manifest_payload.read().decode("utf-8"))
                )
                checks.append(
                    VerifyCheck(
                        name="manifest_parseable",
                        passed=True,
                        message="Manifest parsed successfully",
                    )
                )
                schema_ok = manifest.schema_version in SUPPORTED_SCHEMA_VERSIONS
                checks.append(
                    VerifyCheck(
                        name="schema_supported",
                        passed=schema_ok,
                        message=(
                            "Manifest schema version supported"
                            if schema_ok
                            else f"Unsupported schema version: {manifest.schema_version}"
                        ),
                    )
                )
                if not schema_ok:
                    return VerifyResult(valid=False, checks=checks, warnings=warnings)

                for asset in manifest.assets:
                    if not asset.included:
                        continue
                    members_for_asset = _matching_asset_members(
                        members,
                        archive_root,
                        asset.relative_path,
                    )
                    present = bool(members_for_asset)
                    checks.append(
                        VerifyCheck(
                            name=f"asset_present:{asset.relative_path}",
                            passed=present,
                            message=(
                                "Asset entries present in archive"
                                if present
                                else f"Asset missing from archive: {asset.relative_path}"
                            ),
                        )
                    )
                    if not present:
                        continue
                    checksum = _compute_archive_checksum(
                        archive=archive,
                        archive_root=archive_root,
                        asset=asset,
                    )
                    checks.append(
                        VerifyCheck(
                            name=f"checksum:{asset.relative_path}",
                            passed=checksum == asset.checksum,
                            message=(
                                "Asset checksum verified"
                                if checksum == asset.checksum
                                else f"Checksum mismatch for {asset.relative_path}"
                            ),
                        )
                    )
        except (
            OSError,
            tarfile.TarError,
            KeyError,
            json.JSONDecodeError,
            BackupError,
            ValueError,
        ) as exc:
            checks.append(VerifyCheck(name="archive_parse", passed=False, message=str(exc)))
            return VerifyResult(valid=False, checks=checks, warnings=warnings)

        return VerifyResult(
            valid=all(check.passed for check in checks),
            checks=checks,
            warnings=warnings,
        )

    def list_backups(self) -> BackupListResponse:
        """List known backup archives from disk."""
        backups = [
            self._load_summary(path)
            for path in sorted(self._backup_dir.glob("*.tar.gz"), reverse=True)
        ]
        return BackupListResponse(backups=backups, count=len(backups))

    def get_backup_detail(self, backup_id: str) -> BackupDetailResponse | None:
        """Return the summary and manifest for one backup."""
        archive_path = self.resolve_backup_path(backup_id)
        if archive_path is None:
            return None
        return BackupDetailResponse(
            backup=self._load_summary(archive_path),
            manifest=self._load_manifest(archive_path),
        )

    def load_manifest(self, archive_path: Path) -> BackupManifest:
        """Load the manifest for one archive path."""
        return self._load_manifest(archive_path)

    def resolve_target_path(self, relative_path: str) -> Path | None:
        """Resolve a manifest asset path to the current live target path."""
        for candidate in self._asset_candidates():
            if candidate.relative_path == relative_path:
                return candidate.source_path.resolve() if candidate.source_path else None
        return None

    def resolve_backup_path(self, backup_id: str) -> Path | None:
        """Resolve a backup ID to an archive path."""
        for archive_path in sorted(self._backup_dir.glob("*.tar.gz"), reverse=True):
            try:
                manifest = self._load_manifest(archive_path)
            except (OSError, tarfile.TarError, KeyError, json.JSONDecodeError, ValueError):
                continue
            if manifest.backup_id == backup_id:
                return archive_path
        return None

    def _materialize_asset(self, candidate: _AssetCandidate, mode: BackupMode) -> BackupAsset:
        if candidate.source_path is None:
            return BackupAsset(
                relative_path=candidate.relative_path,
                asset_type=candidate.asset_type,
                included=False,
                exclusion_reason=candidate.missing_reason,
            )

        source = candidate.source_path.resolve()
        if mode not in candidate.included_modes:
            return BackupAsset(
                relative_path=candidate.relative_path,
                asset_type=candidate.asset_type,
                included=False,
                exclusion_reason=(
                    "Excluded in config-only mode"
                    if mode == BackupMode.CONFIG_ONLY
                    else "Workspace excluded by backup mode"
                ),
                is_directory=source.is_dir(),
                source_path=str(source),
            )
        if not source.exists():
            return BackupAsset(
                relative_path=candidate.relative_path,
                asset_type=candidate.asset_type,
                included=False,
                exclusion_reason=candidate.missing_reason,
                is_directory=source.is_dir(),
                source_path=str(source),
            )
        if self._source_contains_backup_dir(source):
            return BackupAsset(
                relative_path=candidate.relative_path,
                asset_type=candidate.asset_type,
                included=False,
                exclusion_reason="Backup output directory is nested under the source root",
                is_directory=source.is_dir(),
                source_path=str(source),
            )

        return BackupAsset(
            relative_path=candidate.relative_path,
            asset_type=candidate.asset_type,
            size_bytes=_compute_size(source),
            checksum=_compute_checksum(source),
            included=True,
            is_directory=source.is_dir(),
            source_path=str(source),
        )

    def _load_summary(self, archive_path: Path) -> BackupSummary:
        """Build a list summary from an archive manifest."""
        try:
            manifest = self._load_manifest(archive_path)
            return BackupSummary(
                backup_id=manifest.backup_id,
                created_at=manifest.created_at,
                archive_path=str(archive_path),
                mode=manifest.backup_mode,
                label=str(manifest.metadata.get("label", "")),
                size_bytes=archive_path.stat().st_size,
                asset_count=sum(1 for asset in manifest.assets if asset.included),
            )
        except (OSError, tarfile.TarError, KeyError, json.JSONDecodeError, ValueError) as exc:
            return BackupSummary(
                backup_id=archive_path.stem,
                archive_path=str(archive_path),
                size_bytes=archive_path.stat().st_size if archive_path.exists() else 0,
                asset_count=0,
                warnings=[f"Manifest unreadable: {exc}"],
            )

    def _load_manifest(self, archive_path: Path) -> BackupManifest:
        with tarfile.open(archive_path, "r:gz") as archive:
            members = archive.getmembers()
            roots = {PurePosixPath(member.name).parts[0] for member in members if member.name}
            if len(roots) != 1:
                raise BackupError("Archive must contain exactly one top-level root")
            root = next(iter(roots))
            manifest_member = archive.getmember(f"{root}/{MANIFEST_FILENAME}")
            payload = archive.extractfile(manifest_member)
            if payload is None:
                raise BackupError("Manifest payload is missing")
            return BackupManifest.model_validate(json.loads(payload.read().decode("utf-8")))

    def _asset_candidates(self) -> list[_AssetCandidate]:
        return [
            _AssetCandidate(
                relative_path="config/.env",
                asset_type="config",
                source_path=self._optional_path(self._app_root / ".env"),
                included_modes=frozenset(
                    {BackupMode.FULL, BackupMode.CONFIG_ONLY, BackupMode.NO_WORKSPACE}
                ),
                missing_reason="No root .env file found",
            ),
            _AssetCandidate(
                relative_path="config/agent-definitions",
                asset_type="agent_definitions",
                source_path=self._resolve_setting_path(self._settings.agent_definitions_dir),
                included_modes=frozenset(
                    {BackupMode.FULL, BackupMode.CONFIG_ONLY, BackupMode.NO_WORKSPACE}
                ),
            ),
            _AssetCandidate(
                relative_path="config/workflow-definitions",
                asset_type="workflow_definitions",
                source_path=self._resolve_setting_path(self._settings.synthetic_env_workflow_dir),
                included_modes=frozenset(
                    {BackupMode.FULL, BackupMode.CONFIG_ONLY, BackupMode.NO_WORKSPACE}
                ),
            ),
            _AssetCandidate(
                relative_path="config/skills",
                asset_type="skills",
                source_path=self._resolve_setting_path(self._settings.skill_definitions_dir),
                included_modes=frozenset(
                    {BackupMode.FULL, BackupMode.CONFIG_ONLY, BackupMode.NO_WORKSPACE}
                ),
            ),
            _AssetCandidate(
                relative_path="config/packs",
                asset_type="packs",
                source_path=self._resolve_setting_path(self._settings.pack_definitions_dir),
                included_modes=frozenset(
                    {BackupMode.FULL, BackupMode.CONFIG_ONLY, BackupMode.NO_WORKSPACE}
                ),
            ),
            _AssetCandidate(
                relative_path="config/plugins",
                asset_type="plugins",
                source_path=self._resolve_setting_path(self._settings.plugin_definitions_dir),
                included_modes=frozenset(
                    {BackupMode.FULL, BackupMode.CONFIG_ONLY, BackupMode.NO_WORKSPACE}
                ),
            ),
            _AssetCandidate(
                relative_path="config/hooks",
                asset_type="hooks",
                source_path=self._resolve_setting_path(self._settings.hooks_definitions_dir),
                included_modes=frozenset(
                    {BackupMode.FULL, BackupMode.CONFIG_ONLY, BackupMode.NO_WORKSPACE}
                ),
            ),
            _AssetCandidate(
                relative_path="state/plugin_lifecycle_state.json",
                asset_type="state",
                source_path=self._resolve_setting_path(self._settings.plugin_state_store_path),
                included_modes=frozenset({BackupMode.FULL, BackupMode.NO_WORKSPACE}),
            ),
            _AssetCandidate(
                relative_path="state/orchestration_state.json",
                asset_type="state",
                source_path=self._resolve_setting_path(
                    self._settings.orchestration_state_store_path
                ),
                included_modes=frozenset({BackupMode.FULL, BackupMode.NO_WORKSPACE}),
                missing_reason="No orchestration state store configured",
            ),
            _AssetCandidate(
                relative_path="state/synthetic_environment_bundles.json",
                asset_type="state",
                source_path=self._resolve_setting_path(
                    self._settings.synthetic_env_bundle_persistence_path
                ),
                included_modes=frozenset({BackupMode.FULL, BackupMode.NO_WORKSPACE}),
            ),
            _AssetCandidate(
                relative_path="state/process-manager",
                asset_type="process_logs",
                source_path=self._resolve_setting_path(self._settings.process_manager_log_dir),
                included_modes=frozenset({BackupMode.FULL, BackupMode.NO_WORKSPACE}),
            ),
            _AssetCandidate(
                relative_path="state/improvement-learning",
                asset_type="state",
                source_path=self._improvement_state_path(),
                included_modes=frozenset({BackupMode.FULL, BackupMode.NO_WORKSPACE}),
                missing_reason="Improvement learning persistence is not file-backed",
            ),
            _AssetCandidate(
                relative_path="sessions",
                asset_type="sessions",
                source_path=self._session_directory(),
                included_modes=frozenset({BackupMode.FULL, BackupMode.NO_WORKSPACE}),
                missing_reason="Operator session directory not configured or not found",
            ),
            *self._database_asset_candidates(),
            _AssetCandidate(
                relative_path="workspace",
                asset_type="workspace",
                source_path=self._optional_path(self._workspace_dir),
                included_modes=frozenset({BackupMode.FULL}),
                missing_reason="Workspace backup is not configured for this runtime",
            ),
        ]

    def _database_asset_candidates(self) -> list[_AssetCandidate]:
        database_paths = {
            "state/databases/component_security_scans.sqlite3": (
                self._settings.component_security_scan_store_db_path
            ),
            "state/databases/p69b.db": self._settings.p69b_db_path,
            "state/databases/ingestion.db": self._settings.ingestion_db_path,
            "state/databases/ingestion_mailbox.db": self._settings.ingestion_mailbox_db_path,
            "state/databases/ingestion_journal.db": self._settings.ingestion_journal_db_path,
            "state/databases/ingestion_task_metrics.db": (
                self._settings.ingestion_task_metrics_db_path
            ),
            "state/databases/ingestion_notification_hooks.db": (
                self._settings.ingestion_notification_hooks_db_path
            ),
            "state/databases/outcomes.db": self._settings.outcomes_db_path,
            "state/databases/ppack_ab.db": self._settings.ppack_v3_ab_db_path,
            "state/databases/agent33_memory.db": self._settings.sqlite_memory_db_path,
            "state/databases/phase23_auth_lifecycle.db": self._settings.phase23_auth_db_path,
            "state/databases/phase23_workspace_lifecycle.db": (
                self._settings.phase23_workspace_db_path
            ),
            "state/databases/improvement_learning_signals.sqlite3": (
                self._settings.improvement_learning_persistence_db_path
            ),
            "state/databases/control_plane.db": self._settings.control_plane_db_path,
        }
        return [
            _AssetCandidate(
                relative_path=relative_path,
                asset_type="database",
                source_path=self._resolve_setting_path(raw_path),
                included_modes=frozenset({BackupMode.FULL, BackupMode.NO_WORKSPACE}),
                missing_reason="Configured database file not found",
            )
            for relative_path, raw_path in database_paths.items()
        ]

    def _resolve_setting_path(self, raw_path: str) -> Path | None:
        stripped = raw_path.strip()
        if not stripped:
            return None
        return self._state_paths.resolve(stripped)

    @staticmethod
    def _optional_path(path: Path | None) -> Path | None:
        return path

    def _improvement_state_path(self) -> Path | None:
        backend = self._settings.improvement_learning_persistence_backend.strip().lower()
        if backend == "file":
            return self._resolve_setting_path(self._settings.improvement_learning_persistence_path)
        if backend in {"db", "sqlite"}:
            return self._resolve_setting_path(
                self._settings.improvement_learning_persistence_db_path
            )
        return None

    def _session_directory(self) -> Path | None:
        base_dir = self._settings.operator_session_base_dir.strip()
        if base_dir:
            return self._resolve_setting_path(base_dir)
        return self._state_paths.default_user_state_dir("sessions")

    def _source_contains_backup_dir(self, source: Path) -> bool:
        return self._backup_dir.resolve().is_relative_to(source.resolve())


def _compute_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(child.stat().st_size for child in sorted(path.rglob("*")) if child.is_file())


def _compute_checksum(path: Path) -> str:
    if path.is_file():
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    digest = hashlib.sha256()
    files = [child for child in sorted(path.rglob("*")) if child.is_file()]
    for child in files:
        relative = child.relative_to(path).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_compute_checksum(child).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _strip_archive_root(name: str, archive_root: str) -> str:
    path = PurePosixPath(name)
    if not path.parts or path.parts[0] != archive_root:
        return ""
    if len(path.parts) == 1:
        return ""
    return PurePosixPath(*path.parts[1:]).as_posix()


def _find_duplicates(items: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for item in items:
        if item in seen and item not in duplicates:
            duplicates.append(item)
        seen.add(item)
    return duplicates


def _matching_asset_members(
    members: list[tarfile.TarInfo], archive_root: str, relative_path: str
) -> list[tarfile.TarInfo]:
    expected = PurePosixPath(relative_path)
    matches: list[tarfile.TarInfo] = []
    for member in members:
        normalized = _strip_archive_root(member.name, archive_root)
        if not normalized:
            continue
        normalized_path = PurePosixPath(normalized)
        if normalized_path == expected or expected in normalized_path.parents:
            matches.append(member)
    return matches


def _compute_archive_checksum(
    *,
    archive: tarfile.TarFile,
    archive_root: str,
    asset: BackupAsset,
) -> str:
    members = _matching_asset_members(archive.getmembers(), archive_root, asset.relative_path)
    if asset.is_directory:
        digest = hashlib.sha256()
        base = PurePosixPath(asset.relative_path)
        for member in sorted(
            (candidate for candidate in members if candidate.isfile()),
            key=lambda item: item.name,
        ):
            normalized = PurePosixPath(_strip_archive_root(member.name, archive_root))
            payload = archive.extractfile(member)
            if payload is None:
                raise BackupError(f"Could not read archive member: {member.name}")
            file_digest = hashlib.sha256(payload.read()).hexdigest()
            digest.update(str(normalized.relative_to(base)).encode("utf-8"))
            digest.update(b"\0")
            digest.update(file_digest.encode("ascii"))
            digest.update(b"\0")
        return digest.hexdigest()

    file_member = next((member for member in members if member.isfile()), None)
    if file_member is None:
        raise BackupError(f"Missing file member for asset: {asset.relative_path}")
    payload = archive.extractfile(file_member)
    if payload is None:
        raise BackupError(f"Could not read archive member: {file_member.name}")
    digest = hashlib.sha256()
    digest.update(payload.read())
    return digest.hexdigest()
