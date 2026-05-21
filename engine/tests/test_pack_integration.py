"""Integration tests for the pack lifecycle: end-to-end flows.

Tests cover: discover -> register skills -> enable/disable per tenant,
install -> load skills -> verify in SkillRegistry, uninstall -> verify
skills removed, upgrade -> old skills replaced, and adapter integration.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

from agent33.packs.adapter import SkillsBenchAdapter

if TYPE_CHECKING:
    from pathlib import Path
from agent33.packs.models import PackSource
from agent33.packs.registry import PackRegistry
from agent33.packs.version import DependencyResolver, VersionConstraint
from agent33.skills.registry import SkillRegistry


def _write_pack(
    base: Path,
    *,
    name: str = "test-pack",
    version: str = "1.0.0",
    skills: list[str] | None = None,
) -> Path:
    """Create a valid pack directory with SKILL.md skills."""
    skill_names = skills or ["default-skill"]
    pack_dir = base / name
    pack_dir.mkdir(parents=True, exist_ok=True)

    skills_yaml = "\n".join(f"  - name: {s}\n    path: skills/{s}" for s in skill_names)

    yaml_content = (
        f'name: "{name}"\n'
        f'version: "{version}"\n'
        f'description: "Pack {name} v{version}"\n'
        f'author: "tester"\n'
        f"tags:\n"
        f"  - integration-test\n"
        f"skills:\n"
        f"{skills_yaml}\n"
    )
    (pack_dir / "PACK.yaml").write_text(yaml_content, encoding="utf-8")

    for sname in skill_names:
        sdir = pack_dir / "skills" / sname
        sdir.mkdir(parents=True, exist_ok=True)
        (sdir / "SKILL.md").write_text(
            f"---\nname: {sname}\nversion: {version}\n"
            f"description: Skill {sname} v{version}\n"
            f"tags:\n  - test\n"
            f"---\n# {sname}\nInstructions for {sname} v{version}.\n",
            encoding="utf-8",
        )

    return pack_dir


class TestPackLifecycle:
    """End-to-end pack lifecycle: discover -> enable -> disable -> uninstall."""

    def test_full_lifecycle(self, tmp_path: Path) -> None:
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()
        _write_pack(packs_dir, name="lifecycle-pack", skills=["skill-a", "skill-b"])

        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=packs_dir, skill_registry=skill_reg)

        # Step 1: Discover
        count = pack_reg.discover()
        assert count == 1

        # Step 2: Verify skills registered
        assert skill_reg.get("lifecycle-pack/skill-a") is not None
        assert skill_reg.get("lifecycle-pack/skill-b") is not None
        assert skill_reg.get("skill-a") is not None  # bare alias

        # Step 3: Enable for tenant
        pack_reg.enable("lifecycle-pack", "tenant-1")
        assert pack_reg.is_enabled("lifecycle-pack", "tenant-1")
        assert not pack_reg.is_enabled("lifecycle-pack", "tenant-2")

        # Step 4: Disable for tenant
        pack_reg.disable("lifecycle-pack", "tenant-1")
        assert not pack_reg.is_enabled("lifecycle-pack", "tenant-1")

        # Step 5: Uninstall
        pack_reg.uninstall("lifecycle-pack")
        assert pack_reg.get("lifecycle-pack") is None
        assert skill_reg.get("lifecycle-pack/skill-a") is None
        assert skill_reg.get("lifecycle-pack/skill-b") is None

    def test_install_then_enable(self, tmp_path: Path) -> None:
        """Install from external path, then enable."""
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        pack_path = _write_pack(source_dir, name="external-pack", skills=["ext-skill"])

        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=packs_dir, skill_registry=skill_reg)

        # Install
        source = PackSource(source_type="local", path=str(pack_path))
        result = pack_reg.install(source)
        assert result.success is True
        assert result.skills_loaded == 1

        # Skills available
        assert skill_reg.get("external-pack/ext-skill") is not None

        # Enable for tenant
        pack_reg.enable("external-pack", "t1")
        enabled = pack_reg.list_enabled("t1")
        assert len(enabled) == 1
        assert enabled[0].name == "external-pack"


class TestPackUpgradeIntegration:
    """Test upgrading packs and verifying skill replacement."""

    def test_upgrade_replaces_skills(self, tmp_path: Path) -> None:
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()
        _write_pack(packs_dir, name="upgradeable", version="1.0.0", skills=["old-skill"])

        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=packs_dir, skill_registry=skill_reg)
        pack_reg.discover()

        # Verify v1 skill
        old_skill = skill_reg.get("upgradeable/old-skill")
        assert old_skill is not None
        assert "v1.0.0" in old_skill.instructions

        # Create v2 with different skill
        new_dir = tmp_path / "new"
        new_dir.mkdir()
        _write_pack(new_dir, name="upgradeable", version="2.0.0", skills=["new-skill"])

        result = pack_reg.upgrade("upgradeable", new_dir / "upgradeable")
        assert result.success is True

        # Old skill gone, new skill present
        assert skill_reg.get("upgradeable/old-skill") is None
        new_skill = skill_reg.get("upgradeable/new-skill")
        assert new_skill is not None
        assert "v2.0.0" in new_skill.instructions


class TestMultiPackInteraction:
    """Test multiple packs and skill name scoping."""

    def test_same_skill_name_different_packs(self, tmp_path: Path) -> None:
        """Two packs with skills of the same name should not collide."""
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()
        _write_pack(packs_dir, name="pack-a", skills=["utils"])
        _write_pack(packs_dir, name="pack-b", version="2.0.0", skills=["utils"])

        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=packs_dir, skill_registry=skill_reg)
        pack_reg.discover()

        # Qualified names should both exist
        skill_a = skill_reg.get("pack-a/utils")
        skill_b = skill_reg.get("pack-b/utils")
        assert skill_a is not None
        assert skill_b is not None

        # Bare alias goes to whichever loaded first (alphabetical: pack-a)
        bare = skill_reg.get("utils")
        assert bare is not None

    def test_tenant_isolation_multiple_packs(self, tmp_path: Path) -> None:
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()
        _write_pack(packs_dir, name="pack-x")
        _write_pack(packs_dir, name="pack-y")

        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=packs_dir, skill_registry=skill_reg)
        pack_reg.discover()

        pack_reg.enable("pack-x", "tenant-a")
        pack_reg.enable("pack-y", "tenant-b")

        assert pack_reg.is_enabled("pack-x", "tenant-a")
        assert not pack_reg.is_enabled("pack-y", "tenant-a")
        assert not pack_reg.is_enabled("pack-x", "tenant-b")
        assert pack_reg.is_enabled("pack-y", "tenant-b")


class TestVersionResolutionIntegration:
    """Test version constraint resolution with realistic scenarios."""

    def test_compatible_range_resolution(self) -> None:
        """Resolve a real-world-ish dependency graph."""
        resolver = DependencyResolver(
            {
                "utils": ["1.0.0", "1.1.0", "1.2.0", "2.0.0"],
                "helpers": ["1.0.0", "1.1.0"],
            }
        )
        result = resolver.resolve(
            [
                ("utils", "^1.0.0"),
                ("helpers", ">=1.0.0, <2.0.0"),
            ]
        )
        assert result.success
        assert result.resolved is not None
        assert result.resolved["utils"] == "1.2.0"
        assert result.resolved["helpers"] == "1.1.0"

    def test_tilde_constraint_limits_minor(self) -> None:
        c = VersionConstraint.parse("~1.2.0")
        from agent33.packs.version import Version

        assert c.satisfies(Version(1, 2, 0))
        assert c.satisfies(Version(1, 2, 5))
        assert not c.satisfies(Version(1, 3, 0))


def _write_pack_with_deps(
    base: Path,
    *,
    name: str = "test-pack",
    version: str = "1.0.0",
    skills: list[str] | None = None,
    pack_deps: list[tuple[str, str]] | None = None,
) -> Path:
    """Create a valid pack directory with optional pack dependencies.

    Args:
        pack_deps: list of (dep_name, version_constraint) tuples.
    """
    skill_names = skills or ["default-skill"]
    pack_dir = base / name
    pack_dir.mkdir(parents=True, exist_ok=True)

    skills_yaml = "\n".join(f"  - name: {s}\n    path: skills/{s}" for s in skill_names)

    deps_yaml = ""
    if pack_deps:
        deps_items = "\n".join(
            f'    - name: "{dn}"\n      version_constraint: "{vc}"' for dn, vc in pack_deps
        )
        deps_yaml = f"dependencies:\n  packs:\n{deps_items}\n"

    yaml_content = (
        f'name: "{name}"\n'
        f'version: "{version}"\n'
        f'description: "Pack {name} v{version}"\n'
        f'author: "tester"\n'
        f"tags:\n"
        f"  - integration-test\n"
        f"{deps_yaml}"
        f"skills:\n"
        f"{skills_yaml}\n"
    )
    (pack_dir / "PACK.yaml").write_text(yaml_content, encoding="utf-8")

    for sname in skill_names:
        sdir = pack_dir / "skills" / sname
        sdir.mkdir(parents=True, exist_ok=True)
        (sdir / "SKILL.md").write_text(
            f"---\nname: {sname}\nversion: {version}\n"
            f"description: Skill {sname} v{version}\n"
            f"tags:\n  - test\n"
            f"---\n# {sname}\nInstructions for {sname} v{version}.\n",
            encoding="utf-8",
        )

    return pack_dir


class TestDependencyValidation:
    """Test install dependency checking and upgrade dependent compatibility."""

    def test_install_with_satisfied_dependencies(self, tmp_path: Path) -> None:
        """Install succeeds when all declared dependencies are present."""
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()

        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=packs_dir, skill_registry=skill_reg)

        # Install the dependency first (no deps of its own)
        dep_dir = tmp_path / "sources"
        _write_pack(dep_dir, name="base-pack", version="1.2.0", skills=["base-skill"])
        source_path = str(dep_dir / "base-pack")
        result_dep = pack_reg.install(PackSource(source_type="local", path=source_path))
        assert result_dep.success is True

        # Now install a pack that depends on base-pack ^1.0.0
        _write_pack_with_deps(
            dep_dir,
            name="consumer-pack",
            version="1.0.0",
            skills=["consumer-skill"],
            pack_deps=[("base-pack", "^1.0.0")],
        )
        result = pack_reg.install(
            PackSource(source_type="local", path=str(dep_dir / "consumer-pack"))
        )
        assert result.success is True
        assert result.skills_loaded == 1

    def test_install_with_missing_dependency(self, tmp_path: Path) -> None:
        """Install fails when a declared dependency is not installed."""
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()

        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=packs_dir, skill_registry=skill_reg)

        dep_dir = tmp_path / "sources"
        _write_pack_with_deps(
            dep_dir,
            name="lonely-pack",
            version="1.0.0",
            skills=["lonely-skill"],
            pack_deps=[("missing-dep", "^1.0.0")],
        )
        result = pack_reg.install(
            PackSource(source_type="local", path=str(dep_dir / "lonely-pack"))
        )
        assert result.success is False
        assert any("Missing dependency" in e for e in result.errors)
        assert any("missing-dep" in e for e in result.errors)
        # Pack should not be registered
        assert pack_reg.get("lonely-pack") is None

    def test_install_with_version_incompatible_dependency(self, tmp_path: Path) -> None:
        """Install fails when dependency exists but version does not satisfy constraint."""
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()

        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=packs_dir, skill_registry=skill_reg)

        # Install base-pack at v1.0.0
        dep_dir = tmp_path / "sources"
        _write_pack(dep_dir, name="base-pack", version="1.0.0", skills=["base-skill"])
        source_path = str(dep_dir / "base-pack")
        result_dep = pack_reg.install(PackSource(source_type="local", path=source_path))
        assert result_dep.success is True

        # Try to install consumer that needs base-pack >=2.0.0
        _write_pack_with_deps(
            dep_dir,
            name="strict-consumer",
            version="1.0.0",
            skills=["strict-skill"],
            pack_deps=[("base-pack", ">=2.0.0")],
        )
        result = pack_reg.install(
            PackSource(source_type="local", path=str(dep_dir / "strict-consumer"))
        )
        assert result.success is False
        assert any("Incompatible dependency" in e for e in result.errors)
        assert any("base-pack" in e for e in result.errors)
        assert pack_reg.get("strict-consumer") is None

    def test_upgrade_that_breaks_dependent(self, tmp_path: Path) -> None:
        """Upgrade fails when the new version breaks a dependent pack's constraint."""
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()

        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=packs_dir, skill_registry=skill_reg)

        dep_dir = tmp_path / "sources"

        # Install base-pack v1.0.0
        _write_pack(dep_dir, name="base-pack", version="1.0.0", skills=["base-skill"])
        pack_reg.install(PackSource(source_type="local", path=str(dep_dir / "base-pack")))

        # Install consumer that requires base-pack ^1.0.0 (i.e., >=1.0.0, <2.0.0)
        _write_pack_with_deps(
            dep_dir,
            name="consumer-pack",
            version="1.0.0",
            skills=["consumer-skill"],
            pack_deps=[("base-pack", "^1.0.0")],
        )
        pack_reg.install(PackSource(source_type="local", path=str(dep_dir / "consumer-pack")))

        # Now try to upgrade base-pack to v2.0.0 -- should fail
        v2_dir = tmp_path / "v2-sources"
        _write_pack(v2_dir, name="base-pack", version="2.0.0", skills=["base-skill-v2"])
        result = pack_reg.upgrade("base-pack", v2_dir / "base-pack", "2.0.0")
        assert result.success is False
        assert any("Upgrade would break dependent" in e for e in result.errors)
        assert any("consumer-pack" in e for e in result.errors)
        # base-pack should still be at v1.0.0
        assert pack_reg.get("base-pack").version == "1.0.0"  # type: ignore[union-attr]

    def test_upgrade_that_satisfies_all_dependents(self, tmp_path: Path) -> None:
        """Upgrade succeeds when the new version satisfies all dependent constraints."""
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()

        skill_reg = SkillRegistry()
        pack_reg = PackRegistry(packs_dir=packs_dir, skill_registry=skill_reg)

        dep_dir = tmp_path / "sources"

        # Install base-pack v1.0.0
        _write_pack(dep_dir, name="base-pack", version="1.0.0", skills=["base-skill"])
        pack_reg.install(PackSource(source_type="local", path=str(dep_dir / "base-pack")))

        # Install consumer that requires base-pack ^1.0.0 (>=1.0.0, <2.0.0)
        _write_pack_with_deps(
            dep_dir,
            name="consumer-pack",
            version="1.0.0",
            skills=["consumer-skill"],
            pack_deps=[("base-pack", "^1.0.0")],
        )
        pack_reg.install(PackSource(source_type="local", path=str(dep_dir / "consumer-pack")))

        # Upgrade base-pack to v1.5.0 -- should succeed
        v15_dir = tmp_path / "v15-sources"
        _write_pack(v15_dir, name="base-pack", version="1.5.0", skills=["base-skill-v15"])
        result = pack_reg.upgrade("base-pack", v15_dir / "base-pack", "1.5.0")
        assert result.success is True
        assert pack_reg.get("base-pack").version == "1.5.0"  # type: ignore[union-attr]


class TestAdapterIntegration:
    """Test adapter loading integrated with skill definitions."""

    def test_skillsbench_skills_have_correct_defaults(self, tmp_path: Path) -> None:
        """Loaded SkillsBench skills should have safe governance defaults."""
        skill_dir = tmp_path / "sb-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            textwrap.dedent("""\
            ---
            name: sb-skill
            description: From SkillsBench
            ---
            # SB Skill
            Do the SkillsBench thing.
            """),
            encoding="utf-8",
        )

        adapter = SkillsBenchAdapter()
        skills = adapter.load(skill_dir)
        assert len(skills) == 1

        skill = skills[0]
        assert skill.name == "sb-skill"
        assert skill.invocation_mode.value == "both"
        assert skill.execution_context.value == "inline"
        assert skill.allowed_tools == []
        assert skill.disallowed_tools == []
        assert skill.approval_required_for == []

    def test_adapter_skills_register_in_skill_registry(self, tmp_path: Path) -> None:
        """Skills loaded via adapter can be registered normally."""
        skill_dir = tmp_path / "adapter-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: adapter-test\ndescription: Via adapter\n---\n# Test\n",
            encoding="utf-8",
        )

        adapter = SkillsBenchAdapter()
        skills = adapter.load(skill_dir)

        reg = SkillRegistry()
        for skill in skills:
            reg.register(skill)

        assert reg.get("adapter-test") is not None
        assert reg.get("adapter-test").description == "Via adapter"  # type: ignore[union-attr]
