"""Tests for pack rollback support."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

import pytest

from agent33.packs.models import PackSource
from agent33.packs.registry import PackRegistry
from agent33.packs.rollback import PackRollbackManager
from agent33.services.orchestration_state import OrchestrationStateStore
from agent33.skills.registry import SkillRegistry

if TYPE_CHECKING:
    from pathlib import Path


def _write_pack(base: Path, *, name: str, version: str) -> Path:
    pack_dir = base / name
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "PACK.yaml").write_text(
        textwrap.dedent(
            f"""\
            name: {name}
            version: {version}
            description: Pack {name}
            author: tester
            skills:
              - name: skill-1
                path: skills/skill-1
            """
        ),
        encoding="utf-8",
    )
    skill_dir = pack_dir / "skills" / "skill-1"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: skill-1\ndescription: Skill\n---\n# Skill\n",
        encoding="utf-8",
    )
    return pack_dir


def _make_manager(
    tmp_path: Path,
) -> tuple[PackRegistry, PackRollbackManager, OrchestrationStateStore]:
    """Create a fresh PackRegistry + PackRollbackManager pair."""
    skill_registry = SkillRegistry()
    pack_registry = PackRegistry(packs_dir=tmp_path / "packs", skill_registry=skill_registry)
    state_store = OrchestrationStateStore(str(tmp_path / "rollback-state.json"))
    rollback_manager = PackRollbackManager(
        pack_registry,
        archive_dir=tmp_path / "archive",
        state_store=state_store,
    )
    return pack_registry, rollback_manager, state_store


def test_pack_rollback_restores_archived_version_and_enablement(tmp_path: Path) -> None:
    skill_registry = SkillRegistry()
    pack_registry = PackRegistry(packs_dir=tmp_path / "packs", skill_registry=skill_registry)
    v1 = _write_pack(tmp_path / "sources" / "v1", name="ops-pack", version="1.0.0")
    v2 = _write_pack(tmp_path / "sources" / "v2", name="ops-pack", version="2.0.0")
    state_store = OrchestrationStateStore(str(tmp_path / "rollback-state.json"))
    rollback_manager = PackRollbackManager(
        pack_registry,
        archive_dir=tmp_path / "archive",
        state_store=state_store,
    )

    install_result = pack_registry.install(PackSource(source_type="local", path=str(v1)))
    assert install_result.success is True
    pack_registry.enable("ops-pack", "tenant-a")

    rollback_manager.archive_current("ops-pack")
    upgrade_result = pack_registry.upgrade("ops-pack", v2, "2.0.0")
    assert upgrade_result.success is True

    rollback_result, archived = rollback_manager.rollback("ops-pack", version="1.0.0")

    assert rollback_result.success is True
    assert archived.version == "1.0.0"
    assert pack_registry.get("ops-pack").version == "1.0.0"  # type: ignore[union-attr]
    assert pack_registry.is_enabled("ops-pack", "tenant-a") is True


def test_rollback_no_archive_raises_error(tmp_path: Path) -> None:
    """Rollback when no archive exists should raise ValueError."""
    pack_registry, rollback_manager, _ = _make_manager(tmp_path)
    v1 = _write_pack(tmp_path / "sources" / "v1", name="my-pack", version="1.0.0")
    result = pack_registry.install(PackSource(source_type="local", path=str(v1)))
    assert result.success is True

    with pytest.raises(ValueError, match="No archived rollback revision available"):
        rollback_manager.rollback("my-pack")


def test_rollback_pack_not_installed_raises_error(tmp_path: Path) -> None:
    """Rollback on a pack that is not installed should raise ValueError."""
    _, rollback_manager, _ = _make_manager(tmp_path)

    with pytest.raises(ValueError, match="not installed"):
        rollback_manager.rollback("nonexistent-pack")


def test_archive_current_appears_in_list(tmp_path: Path) -> None:
    """After archiving, the archived revision appears in list_archived_versions."""
    pack_registry, rollback_manager, _ = _make_manager(tmp_path)
    v1 = _write_pack(tmp_path / "sources" / "v1", name="alpha-pack", version="1.0.0")
    pack_registry.install(PackSource(source_type="local", path=str(v1)))

    revision = rollback_manager.archive_current("alpha-pack")

    listed = rollback_manager.list_archived_versions("alpha-pack")
    assert len(listed) == 1
    assert listed[0].pack_name == "alpha-pack"
    assert listed[0].version == "1.0.0"
    assert listed[0].archive_path == revision.archive_path


def test_archive_then_rollback_restores_pack(tmp_path: Path) -> None:
    """Archive v1, upgrade to v2, rollback restores v1."""
    pack_registry, rollback_manager, _ = _make_manager(tmp_path)
    v1 = _write_pack(tmp_path / "sources" / "v1", name="beta-pack", version="1.0.0")
    v2 = _write_pack(tmp_path / "sources" / "v2", name="beta-pack", version="2.0.0")

    pack_registry.install(PackSource(source_type="local", path=str(v1)))
    assert pack_registry.get("beta-pack").version == "1.0.0"  # type: ignore[union-attr]

    rollback_manager.archive_current("beta-pack")
    pack_registry.upgrade("beta-pack", v2, "2.0.0")
    assert pack_registry.get("beta-pack").version == "2.0.0"  # type: ignore[union-attr]

    result, archived = rollback_manager.rollback("beta-pack", version="1.0.0")
    assert result.success is True
    assert archived.version == "1.0.0"
    assert pack_registry.get("beta-pack").version == "1.0.0"  # type: ignore[union-attr]


def test_rollback_to_specific_version_among_multiple(tmp_path: Path) -> None:
    """When multiple archived versions exist, rollback selects the specified one."""
    pack_registry, rollback_manager, _ = _make_manager(tmp_path)
    v1 = _write_pack(tmp_path / "sources" / "v1", name="multi-pack", version="1.0.0")
    v2 = _write_pack(tmp_path / "sources" / "v2", name="multi-pack", version="2.0.0")
    v3 = _write_pack(tmp_path / "sources" / "v3", name="multi-pack", version="3.0.0")

    pack_registry.install(PackSource(source_type="local", path=str(v1)))
    rollback_manager.archive_current("multi-pack")

    pack_registry.upgrade("multi-pack", v2, "2.0.0")
    rollback_manager.archive_current("multi-pack")

    pack_registry.upgrade("multi-pack", v3, "3.0.0")
    assert pack_registry.get("multi-pack").version == "3.0.0"  # type: ignore[union-attr]

    # Rollback to v1 specifically, skipping v2
    result, archived = rollback_manager.rollback("multi-pack", version="1.0.0")
    assert result.success is True
    assert archived.version == "1.0.0"
    assert pack_registry.get("multi-pack").version == "1.0.0"  # type: ignore[union-attr]


def test_state_persistence_round_trip(tmp_path: Path) -> None:
    """Archives survive a manager recreate (state persistence via state store)."""
    pack_registry, rollback_manager, state_store = _make_manager(tmp_path)
    v1 = _write_pack(tmp_path / "sources" / "v1", name="persist-pack", version="1.0.0")
    pack_registry.install(PackSource(source_type="local", path=str(v1)))
    rollback_manager.archive_current("persist-pack")

    # Verify archive exists
    assert len(rollback_manager.list_archived_versions("persist-pack")) == 1

    # Recreate the manager from the same state store on disk
    state_store_2 = OrchestrationStateStore(str(tmp_path / "rollback-state.json"))
    rollback_manager_2 = PackRollbackManager(
        pack_registry,
        archive_dir=tmp_path / "archive",
        state_store=state_store_2,
    )

    listed = rollback_manager_2.list_archived_versions("persist-pack")
    assert len(listed) == 1
    assert listed[0].pack_name == "persist-pack"
    assert listed[0].version == "1.0.0"


def test_multiple_archives_correct_ordering(tmp_path: Path) -> None:
    """Multiple archives of the same pack are listed newest-first."""
    pack_registry, rollback_manager, _ = _make_manager(tmp_path)
    v1 = _write_pack(tmp_path / "sources" / "v1", name="order-pack", version="1.0.0")
    v2 = _write_pack(tmp_path / "sources" / "v2", name="order-pack", version="2.0.0")
    v3 = _write_pack(tmp_path / "sources" / "v3", name="order-pack", version="3.0.0")

    pack_registry.install(PackSource(source_type="local", path=str(v1)))
    rollback_manager.archive_current("order-pack")

    pack_registry.upgrade("order-pack", v2, "2.0.0")
    rollback_manager.archive_current("order-pack")

    pack_registry.upgrade("order-pack", v3, "3.0.0")
    rollback_manager.archive_current("order-pack")

    listed = rollback_manager.list_archived_versions("order-pack")
    assert len(listed) == 3
    # list_archived_versions returns reversed (newest first)
    assert listed[0].version == "3.0.0"
    assert listed[1].version == "2.0.0"
    assert listed[2].version == "1.0.0"


def test_archive_nonexistent_pack_raises_error(tmp_path: Path) -> None:
    """Archiving a pack that is not installed should raise ValueError."""
    _, rollback_manager, _ = _make_manager(tmp_path)

    with pytest.raises(ValueError, match="not installed"):
        rollback_manager.archive_current("ghost-pack")


def test_list_archived_versions_empty_for_unknown_pack(tmp_path: Path) -> None:
    """Listing archives for a pack that was never archived returns empty list."""
    _, rollback_manager, _ = _make_manager(tmp_path)

    listed = rollback_manager.list_archived_versions("never-archived")
    assert listed == []


def test_rollback_without_version_picks_previous(tmp_path: Path) -> None:
    """Rollback without specifying a version picks the most recent different version."""
    pack_registry, rollback_manager, _ = _make_manager(tmp_path)
    v1 = _write_pack(tmp_path / "sources" / "v1", name="auto-pack", version="1.0.0")
    v2 = _write_pack(tmp_path / "sources" / "v2", name="auto-pack", version="2.0.0")

    pack_registry.install(PackSource(source_type="local", path=str(v1)))
    rollback_manager.archive_current("auto-pack")
    pack_registry.upgrade("auto-pack", v2, "2.0.0")

    # Rollback without specifying version should pick v1
    result, archived = rollback_manager.rollback("auto-pack")
    assert result.success is True
    assert archived.version == "1.0.0"
    assert pack_registry.get("auto-pack").version == "1.0.0"  # type: ignore[union-attr]
