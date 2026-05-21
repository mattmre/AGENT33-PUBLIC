"""Tests for platform backup creation, listing, and verification."""

from __future__ import annotations

import json
import tarfile
from pathlib import Path

import pytest

from agent33.backup.archive import MANIFEST_FILENAME, write_tar_gz
from agent33.backup.manifest import BackupMode
from agent33.backup.service import BackupService
from agent33.config import Settings


def _seed_tree(root: Path) -> None:
    (root / ".env").write_text("API_SECRET_KEY=test\n", encoding="utf-8")
    (root / "agent-definitions").mkdir(parents=True, exist_ok=True)
    (root / "agent-definitions" / "alpha.yaml").write_text("name: alpha\n", encoding="utf-8")
    (root / "workflow-definitions").mkdir(parents=True, exist_ok=True)
    (root / "workflow-definitions" / "flow.yaml").write_text("steps: []\n", encoding="utf-8")
    (root / "skills").mkdir(parents=True, exist_ok=True)
    (root / "skills" / "skill.md").write_text("# Skill\n", encoding="utf-8")
    (root / "packs").mkdir(parents=True, exist_ok=True)
    (root / "packs" / "pack.yaml").write_text("name: pack\n", encoding="utf-8")
    (root / "plugins").mkdir(parents=True, exist_ok=True)
    (root / "plugins" / "plugin.yaml").write_text("name: plugin\n", encoding="utf-8")
    (root / "hook-definitions").mkdir(parents=True, exist_ok=True)
    (root / "hook-definitions" / "hook.sh").write_text("echo hook\n", encoding="utf-8")
    (root / "var").mkdir(parents=True, exist_ok=True)
    (root / "var" / "plugin_lifecycle_state.json").write_text("{}", encoding="utf-8")
    (root / "var" / "synthetic_environment_bundles.json").write_text("[]", encoding="utf-8")
    (root / "var" / "improvement_learning_signals.json").write_text("{}", encoding="utf-8")
    (root / "var" / "process-manager").mkdir(parents=True, exist_ok=True)
    (root / "var" / "process-manager" / "proc.log").write_text("hello\n", encoding="utf-8")
    (root / "sessions").mkdir(parents=True, exist_ok=True)
    (root / "sessions" / "session.json").write_text('{"id":"s1"}', encoding="utf-8")


def _settings(root: Path) -> Settings:
    return Settings(
        agent_definitions_dir="agent-definitions",
        synthetic_env_workflow_dir="workflow-definitions",
        skill_definitions_dir="skills",
        pack_definitions_dir="packs",
        plugin_definitions_dir="plugins",
        hooks_definitions_dir="hook-definitions",
        plugin_state_store_path="var/plugin_lifecycle_state.json",
        synthetic_env_bundle_persistence_path="var/synthetic_environment_bundles.json",
        process_manager_log_dir="var/process-manager",
        improvement_learning_persistence_backend="file",
        improvement_learning_persistence_path="var/improvement_learning_signals.json",
        operator_session_base_dir=str(root / "sessions"),
        backup_dir=str(root / "backups"),
    )


def test_inventory_allows_absolute_external_config_sources(tmp_path: Path) -> None:
    _seed_tree(tmp_path)
    external_defs = tmp_path / "external-agent-definitions"
    external_defs.mkdir()
    (external_defs / "beta.yaml").write_text("name: beta\n", encoding="utf-8")

    settings = _settings(tmp_path).model_copy(
        update={"agent_definitions_dir": str(external_defs.resolve())}
    )
    service = BackupService(
        backup_dir=tmp_path / "backups",
        settings=settings,
        app_root=tmp_path,
        workspace_dir=None,
    )

    inventory = service.inventory(mode=BackupMode.CONFIG_ONLY)
    asset = next(
        asset for asset in inventory.assets if asset.relative_path == "config/agent-definitions"
    )

    assert asset.included is True
    assert Path(asset.source_path) == external_defs.resolve()


@pytest.mark.asyncio()
async def test_create_backup_round_trip_and_list(tmp_path: Path) -> None:
    _seed_tree(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("workspace-data", encoding="utf-8")
    service = BackupService(
        backup_dir=tmp_path / "backups",
        settings=_settings(tmp_path),
        app_root=tmp_path,
        workspace_dir=workspace,
    )

    result = await service.create(mode=BackupMode.FULL, label="nightly", creator="tester")

    assert result.success is True
    assert Path(result.archive_path).exists()
    assert result.asset_count > 0
    listing = service.list_backups()
    assert listing.count == 1
    assert listing.backups[0].label == "nightly"
    detail = service.get_backup_detail(result.backup_id)
    assert detail is not None
    assert detail.manifest.backup_id == result.backup_id
    assert any(
        asset.relative_path == "workspace" and asset.included for asset in detail.manifest.assets
    )


def test_inventory_respects_config_only_mode(tmp_path: Path) -> None:
    _seed_tree(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    service = BackupService(
        backup_dir=tmp_path / "backups",
        settings=_settings(tmp_path),
        app_root=tmp_path,
        workspace_dir=workspace,
    )

    inventory = service.inventory(mode=BackupMode.CONFIG_ONLY)
    workspace_asset = next(
        asset for asset in inventory.assets if asset.relative_path == "workspace"
    )
    state_asset = next(
        asset
        for asset in inventory.assets
        if asset.relative_path == "state/plugin_lifecycle_state.json"
    )

    assert workspace_asset.included is False
    assert state_asset.included is False
    assert any(
        asset.relative_path == "config/agent-definitions" and asset.included
        for asset in inventory.assets
    )


def test_inventory_includes_configured_database_files(tmp_path: Path) -> None:
    _seed_tree(tmp_path)
    db_path = tmp_path / "var" / "ingestion.db"
    db_path.write_bytes(b"sqlite-data")
    service = BackupService(
        backup_dir=tmp_path / "backups",
        settings=_settings(tmp_path),
        app_root=tmp_path,
        workspace_dir=None,
    )

    inventory = service.inventory(mode=BackupMode.NO_WORKSPACE)
    db_asset = next(
        asset
        for asset in inventory.assets
        if asset.relative_path == "state/databases/ingestion.db"
    )

    assert db_asset.included is True
    assert db_asset.asset_type == "database"
    assert Path(db_asset.source_path) == db_path.resolve()
    assert all(asset.relative_path != "database-export.json" for asset in inventory.assets)


@pytest.mark.asyncio()
async def test_verify_detects_checksum_mismatch(tmp_path: Path) -> None:
    _seed_tree(tmp_path)
    service = BackupService(
        backup_dir=tmp_path / "backups",
        settings=_settings(tmp_path),
        app_root=tmp_path,
        workspace_dir=None,
    )
    created = await service.create(mode=BackupMode.NO_WORKSPACE, label="verify")
    archive_path = Path(created.archive_path)

    extract_dir = tmp_path / "tampered"
    with tarfile.open(archive_path, "r:gz") as archive:
        archive.extractall(extract_dir)
    root_dir = next(extract_dir.iterdir())
    manifest_path = root_dir / MANIFEST_FILENAME
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    first_included = next(asset for asset in payload["assets"] if asset["included"])
    first_included["checksum"] = "bad-checksum"
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    tampered_archive = tmp_path / "backups" / "tampered.tar.gz"
    write_tar_gz(root_dir, tampered_archive)

    verify = await service.verify(tampered_archive)

    assert verify.valid is False
    assert any(
        check.name.startswith("checksum:") and check.passed is False for check in verify.checks
    )
