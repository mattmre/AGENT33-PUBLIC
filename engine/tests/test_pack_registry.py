"""Tests for the PackRegistry: discovery, install, uninstall, enable/disable, search.

Tests cover: pack discovery from directories, install from local path,
uninstall with and without dependents, tenant-scoped enable/disable,
search, upgrade/downgrade, and skill registration/unregistration.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from agent33.packs import marketplace as marketplace_module
from agent33.packs.marketplace import LocalPackMarketplace
from agent33.packs.models import PackSource
from agent33.packs.registry import PackRegistry
from agent33.skills.registry import SkillRegistry


def _write_pack(
    base: Path,
    *,
    name: str = "test-pack",
    version: str = "1.0.0",
    skills: list[str] | None = None,
    dependencies: str = "",
) -> Path:
    """Create a pack directory with skills."""
    skill_names = skills or ["my-skill"]

    pack_dir = base / name
    pack_dir.mkdir(parents=True, exist_ok=True)

    skills_yaml = "\n".join(f"  - name: {s}\n    path: skills/{s}" for s in skill_names)
    deps_section = f"\ndependencies:\n{dependencies}" if dependencies else ""

    yaml_content = (
        f'name: "{name}"\n'
        f'version: "{version}"\n'
        f'description: "Pack {name}"\n'
        f'author: "tester"\n'
        f"tags:\n"
        f"  - test\n"
        f"skills:\n"
        f"{skills_yaml}\n"
        f"{deps_section}\n"
    )
    (pack_dir / "PACK.yaml").write_text(yaml_content, encoding="utf-8")

    for sname in skill_names:
        sdir = pack_dir / "skills" / sname
        sdir.mkdir(parents=True, exist_ok=True)
        (sdir / "SKILL.md").write_text(
            f"---\nname: {sname}\nversion: {version}\n"
            f"description: Skill {sname} from {name}\n"
            f"---\n# {sname}\nInstructions for {sname}.\n",
            encoding="utf-8",
        )

    return pack_dir


class TestPackRegistryDiscovery:
    """Test pack discovery from directories."""

    def test_discover_single_pack(self, tmp_path: Path) -> None:
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()
        _write_pack(packs_dir, name="alpha")

        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=packs_dir, skill_registry=skill_reg)
        count = pack_reg.discover()
        assert count == 1
        assert pack_reg.get("alpha") is not None
        assert pack_reg.get("alpha").version == "1.0.0"  # type: ignore[union-attr]

    def test_discover_multiple_packs(self, tmp_path: Path) -> None:
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()
        _write_pack(packs_dir, name="alpha")
        _write_pack(packs_dir, name="beta")

        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=packs_dir, skill_registry=skill_reg)
        count = pack_reg.discover()
        assert count == 2
        assert pack_reg.count == 2

    def test_discover_skips_non_pack_dirs(self, tmp_path: Path) -> None:
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()
        _write_pack(packs_dir, name="valid")
        # A non-pack directory (no PACK.yaml)
        (packs_dir / "not-a-pack").mkdir()
        (packs_dir / "not-a-pack" / "README.md").write_text("not a pack")

        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=packs_dir, skill_registry=skill_reg)
        count = pack_reg.discover()
        assert count == 1

    def test_discover_missing_directory(self, tmp_path: Path) -> None:
        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(
            packs_dir=tmp_path / "nonexistent",
            skill_registry=skill_reg,
        )
        count = pack_reg.discover()
        assert count == 0

    def test_discover_registers_skills(self, tmp_path: Path) -> None:
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()
        _write_pack(packs_dir, name="alpha", skills=["skill-a", "skill-b"])

        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=packs_dir, skill_registry=skill_reg)
        pack_reg.discover()

        # Qualified names registered
        assert skill_reg.get("alpha/skill-a") is not None
        assert skill_reg.get("alpha/skill-b") is not None
        # Bare aliases registered
        assert skill_reg.get("skill-a") is not None
        assert skill_reg.get("skill-b") is not None


class TestPackRegistryInstall:
    """Test pack installation from local paths."""

    def test_install_local_pack(self, tmp_path: Path) -> None:
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()
        pack_path = _write_pack(tmp_path, name="installable")

        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=packs_dir, skill_registry=skill_reg)

        source = PackSource(source_type="local", path=str(pack_path))
        result = pack_reg.install(source)

        assert result.success is True
        assert result.pack_name == "installable"
        assert result.skills_loaded == 1
        assert pack_reg.get("installable") is not None

    def test_install_already_installed(self, tmp_path: Path) -> None:
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()
        pack_path = _write_pack(tmp_path, name="dupe")

        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=packs_dir, skill_registry=skill_reg)

        source = PackSource(source_type="local", path=str(pack_path))
        result1 = pack_reg.install(source)
        assert result1.success is True

        result2 = pack_reg.install(source)
        assert result2.success is False
        assert "already installed" in result2.errors[0]

    def test_install_nonexistent_path(self, tmp_path: Path) -> None:
        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=tmp_path, skill_registry=skill_reg)

        source = PackSource(source_type="local", path=str(tmp_path / "nope"))
        result = pack_reg.install(source)
        assert result.success is False
        assert "not found" in result.errors[0]

    def test_install_marketplace_requires_configured_marketplace(self, tmp_path: Path) -> None:
        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=tmp_path / "packs", skill_registry=skill_reg)

        result = pack_reg.install(PackSource(source_type="marketplace", name="cloud-pack"))

        assert result.success is False
        assert result.pack_name == "cloud-pack"
        assert result.errors == ["Marketplace registry is not configured"]

    def test_install_marketplace_latest_version(self, tmp_path: Path) -> None:
        skill_reg = SkillRegistry()
        marketplace_dir = tmp_path / "marketplace"
        _write_pack(marketplace_dir / "v1", name="cloud-pack", version="1.0.0")
        _write_pack(marketplace_dir / "v2", name="cloud-pack", version="2.0.0")
        pack_reg = PackRegistry(
            packs_dir=tmp_path / "packs",
            skill_registry=skill_reg,
            marketplace=LocalPackMarketplace(marketplace_dir),
        )

        source = PackSource(source_type="marketplace", name="cloud-pack")
        result = pack_reg.install(source)

        assert result.success is True
        assert result.version == "2.0.0"
        installed = pack_reg.get("cloud-pack")
        assert installed is not None
        assert installed.version == "2.0.0"
        assert installed.source == "marketplace"

    def test_install_marketplace_specific_version(self, tmp_path: Path) -> None:
        skill_reg = SkillRegistry()
        marketplace_dir = tmp_path / "marketplace"
        _write_pack(marketplace_dir / "v1", name="cloud-pack", version="1.0.0")
        _write_pack(marketplace_dir / "v2", name="cloud-pack", version="2.0.0")
        pack_reg = PackRegistry(
            packs_dir=tmp_path / "packs",
            skill_registry=skill_reg,
            marketplace=LocalPackMarketplace(marketplace_dir),
        )

        source = PackSource(source_type="marketplace", name="cloud-pack", version="1.0.0")
        result = pack_reg.install(source)

        assert result.success is True
        assert result.version == "1.0.0"
        installed = pack_reg.get("cloud-pack")
        assert installed is not None
        assert installed.version == "1.0.0"

    def test_install_marketplace_missing_pack(self, tmp_path: Path) -> None:
        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(
            packs_dir=tmp_path / "packs",
            skill_registry=skill_reg,
            marketplace=LocalPackMarketplace(tmp_path / "marketplace"),
        )

        result = pack_reg.install(PackSource(source_type="marketplace", name="missing-pack"))

        assert result.success is False
        assert result.errors == ["Marketplace pack 'missing-pack' was not found"]

    def test_install_marketplace_requires_name(self, tmp_path: Path) -> None:
        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(
            packs_dir=tmp_path / "packs",
            skill_registry=skill_reg,
            marketplace=LocalPackMarketplace(tmp_path / "marketplace"),
        )

        result = pack_reg.install(PackSource(source_type="marketplace"))

        assert result.success is False
        assert result.pack_name == "unknown"
        assert result.errors == ["Marketplace installs require a pack name"]


class TestLocalPackMarketplace:
    """Test the filesystem-backed marketplace catalog."""

    def test_catalog_reads_are_cached_until_refresh(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        marketplace_dir = tmp_path / "marketplace"
        _write_pack(marketplace_dir / "v1", name="alpha-pack", version="1.0.0")
        _write_pack(marketplace_dir / "v2", name="alpha-pack", version="2.0.0")
        marketplace = LocalPackMarketplace(marketplace_dir)

        call_count = 0
        original_loader = marketplace_module.load_pack_manifest

        def _counting_loader(pack_dir: Path):  # type: ignore[no-untyped-def]
            nonlocal call_count
            call_count += 1
            return original_loader(pack_dir)

        monkeypatch.setattr(marketplace_module, "load_pack_manifest", _counting_loader)

        assert [pack.name for pack in marketplace.list_packs()] == ["alpha-pack"]
        assert call_count == 2

        assert [pack.name for pack in marketplace.search("alpha")] == ["alpha-pack"]
        assert marketplace.get_pack("alpha-pack") is not None
        assert [item.version for item in marketplace.list_versions("alpha-pack")] == [
            "2.0.0",
            "1.0.0",
        ]
        assert marketplace.resolve("alpha-pack", "1.0.0") is not None
        assert call_count == 2

        _write_pack(marketplace_dir / "v3", name="beta-pack", version="1.0.0")
        assert [pack.name for pack in marketplace.list_packs()] == ["alpha-pack"]

        marketplace.refresh()

        assert [pack.name for pack in marketplace.list_packs()] == ["alpha-pack", "beta-pack"]
        assert call_count == 5

    def test_invalidate_forces_reload_on_next_read(self, tmp_path: Path) -> None:
        marketplace_dir = tmp_path / "marketplace"
        _write_pack(marketplace_dir / "v1", name="alpha-pack", version="1.0.0")
        marketplace = LocalPackMarketplace(marketplace_dir)

        assert [pack.name for pack in marketplace.list_packs()] == ["alpha-pack"]

        _write_pack(marketplace_dir / "v2", name="beta-pack", version="1.0.0")
        marketplace.invalidate()

        assert [pack.name for pack in marketplace.list_packs()] == ["alpha-pack", "beta-pack"]


class TestPackRegistryUninstall:
    """Test pack uninstallation."""

    def test_uninstall_pack(self, tmp_path: Path) -> None:
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()
        _write_pack(packs_dir, name="removable", skills=["s1"])

        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=packs_dir, skill_registry=skill_reg)
        pack_reg.discover()

        assert skill_reg.get("removable/s1") is not None
        result = pack_reg.uninstall("removable")
        assert result is True
        assert pack_reg.get("removable") is None
        # Qualified skill removed
        assert skill_reg.get("removable/s1") is None

    def test_uninstall_not_installed(self, tmp_path: Path) -> None:
        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=tmp_path, skill_registry=skill_reg)

        with pytest.raises(ValueError, match="not installed"):
            pack_reg.uninstall("ghost")

    def test_uninstall_with_dependents_blocked(self, tmp_path: Path) -> None:
        """Cannot uninstall a pack that another pack depends on."""
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()

        # Create base pack
        _write_pack(packs_dir, name="base-utils", skills=["util"])

        # Create dependent pack
        dep_dir = packs_dir / "app-pack"
        dep_dir.mkdir()
        (dep_dir / "PACK.yaml").write_text(
            textwrap.dedent("""\
            name: app-pack
            version: 1.0.0
            description: App
            author: tester
            skills:
              - name: app-skill
                path: skills/app-skill
            dependencies:
              packs:
                - name: base-utils
                  version_constraint: "^1.0.0"
            """),
            encoding="utf-8",
        )
        sdir = dep_dir / "skills" / "app-skill"
        sdir.mkdir(parents=True)
        (sdir / "SKILL.md").write_text(
            "---\nname: app-skill\nversion: 1.0.0\ndescription: App\n---\n# App\n",
            encoding="utf-8",
        )

        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=packs_dir, skill_registry=skill_reg)
        pack_reg.discover()

        with pytest.raises(ValueError, match="required by"):
            pack_reg.uninstall("base-utils")

    def test_uninstall_removes_from_enablement(self, tmp_path: Path) -> None:
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()
        _write_pack(packs_dir, name="temp")

        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=packs_dir, skill_registry=skill_reg)
        pack_reg.discover()
        pack_reg.enable("temp", "tenant-a")
        assert pack_reg.is_enabled("temp", "tenant-a")

        pack_reg.uninstall("temp")
        assert not pack_reg.is_enabled("temp", "tenant-a")


class TestPackRegistryEnableDisable:
    """Test tenant-scoped pack enable/disable."""

    def test_enable_pack(self, tmp_path: Path) -> None:
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()
        _write_pack(packs_dir, name="my-pack")

        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=packs_dir, skill_registry=skill_reg)
        pack_reg.discover()

        result = pack_reg.enable("my-pack", "tenant-1")
        assert result is True
        assert pack_reg.is_enabled("my-pack", "tenant-1")

    def test_enable_idempotent(self, tmp_path: Path) -> None:
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()
        _write_pack(packs_dir, name="idem")

        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=packs_dir, skill_registry=skill_reg)
        pack_reg.discover()

        pack_reg.enable("idem", "t1")
        pack_reg.enable("idem", "t1")
        assert pack_reg.is_enabled("idem", "t1")

    def test_disable_pack(self, tmp_path: Path) -> None:
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()
        _write_pack(packs_dir, name="disableable")

        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=packs_dir, skill_registry=skill_reg)
        pack_reg.discover()

        pack_reg.enable("disableable", "t1")
        assert pack_reg.is_enabled("disableable", "t1")

        pack_reg.disable("disableable", "t1")
        assert not pack_reg.is_enabled("disableable", "t1")

    def test_tenant_isolation(self, tmp_path: Path) -> None:
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()
        _write_pack(packs_dir, name="isolated")

        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=packs_dir, skill_registry=skill_reg)
        pack_reg.discover()

        pack_reg.enable("isolated", "tenant-a")
        assert pack_reg.is_enabled("isolated", "tenant-a")
        assert not pack_reg.is_enabled("isolated", "tenant-b")

    def test_list_enabled(self, tmp_path: Path) -> None:
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()
        _write_pack(packs_dir, name="pack-a")
        _write_pack(packs_dir, name="pack-b")

        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=packs_dir, skill_registry=skill_reg)
        pack_reg.discover()

        pack_reg.enable("pack-a", "t1")
        enabled = pack_reg.list_enabled("t1")
        assert len(enabled) == 1
        assert enabled[0].name == "pack-a"

    def test_enable_not_installed_raises(self, tmp_path: Path) -> None:
        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=tmp_path, skill_registry=skill_reg)

        with pytest.raises(ValueError, match="not installed"):
            pack_reg.enable("ghost", "t1")

    def test_disable_not_installed_raises(self, tmp_path: Path) -> None:
        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=tmp_path, skill_registry=skill_reg)

        with pytest.raises(ValueError, match="not installed"):
            pack_reg.disable("ghost", "t1")


class TestPackRegistrySearch:
    """Test pack search."""

    def test_search_by_name(self, tmp_path: Path) -> None:
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()
        _write_pack(packs_dir, name="kubernetes-ops")
        _write_pack(packs_dir, name="data-science")

        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=packs_dir, skill_registry=skill_reg)
        pack_reg.discover()

        results = pack_reg.search("kubernetes")
        assert len(results) == 1
        assert results[0].name == "kubernetes-ops"

    def test_search_by_tag(self, tmp_path: Path) -> None:
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()
        _write_pack(packs_dir, name="tagged")

        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=packs_dir, skill_registry=skill_reg)
        pack_reg.discover()

        results = pack_reg.search("test")  # "test" is in tags by default
        assert len(results) == 1

    def test_search_no_match(self, tmp_path: Path) -> None:
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()
        _write_pack(packs_dir, name="alpha")

        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=packs_dir, skill_registry=skill_reg)
        pack_reg.discover()

        results = pack_reg.search("zzz-nonexistent")
        assert results == []


class TestPackRegistryUpgrade:
    """Test pack upgrade and downgrade."""

    def test_upgrade_pack(self, tmp_path: Path) -> None:
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()
        _write_pack(packs_dir, name="upgradeable", version="1.0.0")

        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=packs_dir, skill_registry=skill_reg)
        pack_reg.discover()

        assert pack_reg.get("upgradeable").version == "1.0.0"  # type: ignore[union-attr]

        # Create v2
        new_dir = tmp_path / "new"
        new_dir.mkdir()
        _write_pack(new_dir, name="upgradeable", version="2.0.0")

        result = pack_reg.upgrade("upgradeable", new_dir / "upgradeable")
        assert result.success is True
        assert result.version == "2.0.0"
        assert pack_reg.get("upgradeable").version == "2.0.0"  # type: ignore[union-attr]

    def test_upgrade_not_installed(self, tmp_path: Path) -> None:
        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=tmp_path, skill_registry=skill_reg)

        result = pack_reg.upgrade("ghost", tmp_path)
        assert result.success is False
        assert "not installed" in result.errors[0]

    def test_upgrade_name_mismatch(self, tmp_path: Path) -> None:
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()
        _write_pack(packs_dir, name="original")

        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=packs_dir, skill_registry=skill_reg)
        pack_reg.discover()

        wrong_dir = tmp_path / "wrong"
        wrong_dir.mkdir()
        _write_pack(wrong_dir, name="different")

        result = pack_reg.upgrade("original", wrong_dir / "different")
        assert result.success is False
        assert "mismatch" in result.errors[0]


class TestPackRegistryListInstalled:
    """Test list_installed and count properties."""

    def test_list_installed_sorted(self, tmp_path: Path) -> None:
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()
        _write_pack(packs_dir, name="zebra")
        _write_pack(packs_dir, name="alpha")

        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=packs_dir, skill_registry=skill_reg)
        pack_reg.discover()

        installed = pack_reg.list_installed()
        assert [p.name for p in installed] == ["alpha", "zebra"]

    def test_count(self, tmp_path: Path) -> None:
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()
        _write_pack(packs_dir, name="one")

        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=packs_dir, skill_registry=skill_reg)
        assert pack_reg.count == 0
        pack_reg.discover()
        assert pack_reg.count == 1
