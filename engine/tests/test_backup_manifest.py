"""Tests for platform backup manifest models."""

from __future__ import annotations

from datetime import UTC, datetime

from agent33.backup.manifest import BackupAsset, BackupManifest, BackupMode


def test_backup_manifest_serializes_mode_and_assets() -> None:
    created_at = datetime(2026, 3, 12, 21, 0, tzinfo=UTC)
    manifest = BackupManifest(
        backup_id="backup-123",
        created_at=created_at,
        platform="windows",
        runtime_version="0.1.0",
        archive_root="D:/workspace",
        backup_mode=BackupMode.NO_WORKSPACE,
        assets=[
            BackupAsset(
                relative_path="config/agents",
                asset_type="agent_definitions",
                checksum="abc123",
                included=True,
                is_directory=True,
                source_path="D:/workspace/agent-definitions",
            )
        ],
        checksums={"config/agents": "abc123"},
        metadata={"label": "nightly"},
    )

    payload = manifest.model_dump(mode="json")

    assert payload["backup_mode"] == "no-workspace"
    assert payload["assets"][0]["relative_path"] == "config/agents"
    restored = BackupManifest.model_validate(payload)
    assert restored.backup_mode == BackupMode.NO_WORKSPACE
    assert restored.assets[0].is_directory is True
