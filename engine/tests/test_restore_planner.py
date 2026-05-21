"""Tests for read-only restore planning."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agent33.backup.manifest import BackupMode
from agent33.backup.restore_planner import RestorePlanner, RestorePlanningError
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


@pytest.mark.asyncio()
async def test_restore_plan_reports_modified_assets_as_overwrite(tmp_path: Path) -> None:
    _seed_tree(tmp_path)
    service = BackupService(
        backup_dir=tmp_path / "backups",
        settings=_settings(tmp_path),
        app_root=tmp_path,
        workspace_dir=None,
    )
    created = await service.create(mode=BackupMode.NO_WORKSPACE, label="restore")

    (tmp_path / "agent-definitions" / "alpha.yaml").write_text(
        "name: alpha-modified\n",
        encoding="utf-8",
    )
    planner = RestorePlanner(service)

    plan = await planner.plan(created.backup_id, Path(created.archive_path))

    agent_asset = next(
        asset
        for asset in plan.assets_to_restore
        if asset.relative_path == "config/agent-definitions"
    )
    assert agent_asset.action == "overwrite"
    assert any(
        conflict.relative_path == "config/agent-definitions"
        and conflict.conflict_type == "file_modified"
        for conflict in plan.conflicts
    )
    assert any("restore plan only" in warning for warning in plan.warnings)


@pytest.mark.asyncio()
async def test_restore_plan_uses_create_for_missing_targets(tmp_path: Path) -> None:
    _seed_tree(tmp_path)
    service = BackupService(
        backup_dir=tmp_path / "backups",
        settings=_settings(tmp_path),
        app_root=tmp_path,
        workspace_dir=None,
    )
    created = await service.create(mode=BackupMode.NO_WORKSPACE, label="restore")

    shutil.rmtree(tmp_path / "packs")
    planner = RestorePlanner(service)

    plan = await planner.plan(created.backup_id, Path(created.archive_path))

    packs_asset = next(
        asset for asset in plan.assets_to_restore if asset.relative_path == "config/packs"
    )
    assert packs_asset.action == "create"
    assert all(conflict.relative_path != "config/packs" for conflict in plan.conflicts)


@pytest.mark.asyncio()
async def test_restore_execute_requires_confirmation(tmp_path: Path) -> None:
    _seed_tree(tmp_path)
    service = BackupService(
        backup_dir=tmp_path / "backups",
        settings=_settings(tmp_path),
        app_root=tmp_path,
        workspace_dir=None,
    )
    created = await service.create(mode=BackupMode.NO_WORKSPACE, label="restore")
    planner = RestorePlanner(service)

    with pytest.raises(RestorePlanningError, match="confirm=true"):
        await planner.execute(created.backup_id, Path(created.archive_path), confirm=False)


@pytest.mark.asyncio()
async def test_restore_execute_restores_missing_target(tmp_path: Path) -> None:
    _seed_tree(tmp_path)
    service = BackupService(
        backup_dir=tmp_path / "backups",
        settings=_settings(tmp_path),
        app_root=tmp_path,
        workspace_dir=None,
    )
    created = await service.create(mode=BackupMode.NO_WORKSPACE, label="restore")

    shutil.rmtree(tmp_path / "packs")
    planner = RestorePlanner(service)

    result = await planner.execute(created.backup_id, Path(created.archive_path), confirm=True)

    assert result.success is True
    assert any(asset.relative_path == "config/packs" for asset in result.restored_assets)
    assert (tmp_path / "packs" / "pack.yaml").read_text(encoding="utf-8") == "name: pack\n"
    assert any(item == "restored:config/packs:create" for item in result.evidence)


@pytest.mark.asyncio()
async def test_restore_execute_conflict_requires_overwrite_flag(tmp_path: Path) -> None:
    _seed_tree(tmp_path)
    service = BackupService(
        backup_dir=tmp_path / "backups",
        settings=_settings(tmp_path),
        app_root=tmp_path,
        workspace_dir=None,
    )
    created = await service.create(mode=BackupMode.NO_WORKSPACE, label="restore")
    (tmp_path / "agent-definitions" / "alpha.yaml").write_text(
        "name: alpha-modified\n",
        encoding="utf-8",
    )
    planner = RestorePlanner(service)

    with pytest.raises(RestorePlanningError, match="allow_overwrite=true"):
        await planner.execute(created.backup_id, Path(created.archive_path), confirm=True)

    result = await planner.execute(
        created.backup_id,
        Path(created.archive_path),
        confirm=True,
        allow_overwrite=True,
    )

    assert result.success is True
    assert (tmp_path / "agent-definitions" / "alpha.yaml").read_text(encoding="utf-8") == (
        "name: alpha\n"
    )
