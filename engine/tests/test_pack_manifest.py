"""Tests for pack manifest parsing and validation.

Tests cover: PACK.yaml parsing, field validation, name format enforcement,
semver version validation, schema version checks, duplicate skill detection,
and serialization.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from agent33.packs.manifest import PackManifest, manifest_to_dict, parse_pack_yaml
from agent33.packs.models import PackSkillEntry


class TestPackManifest:
    """Test the PackManifest Pydantic model."""

    def test_minimal_valid_manifest(self) -> None:
        manifest = PackManifest(
            name="test-pack",
            version="1.0.0",
            description="A test pack",
            author="tester",
            skills=[PackSkillEntry(name="my-skill", path="skills/my-skill")],
        )
        assert manifest.name == "test-pack"
        assert manifest.version == "1.0.0"
        assert manifest.schema_version == "1"
        assert len(manifest.skills) == 1
        assert manifest.skills[0].name == "my-skill"
        assert manifest.tags == []
        assert manifest.license == ""

    def test_full_manifest(self) -> None:
        manifest = PackManifest(
            name="kubernetes-operations",
            version="2.1.0",
            description="Production-grade Kubernetes skills",
            author="agent33-community",
            license="Apache-2.0",
            homepage="https://example.com",
            repository="https://github.com/example/pack",
            tags=["devops", "kubernetes"],
            category="infrastructure",
            skills=[
                PackSkillEntry(
                    name="k8s-deploy",
                    path="skills/k8s-deploy",
                    description="Deploy workloads",
                    required=True,
                ),
                PackSkillEntry(
                    name="k8s-monitor",
                    path="skills/k8s-monitor",
                    required=False,
                ),
            ],
        )
        assert manifest.name == "kubernetes-operations"
        assert len(manifest.skills) == 2
        assert manifest.skills[0].required is True
        assert manifest.skills[1].required is False
        assert manifest.category == "infrastructure"

    def test_name_lowercase_hyphens_only(self) -> None:
        """Pack names must be lowercase letters, digits, and hyphens."""
        # Valid names
        PackManifest(
            name="a",
            version="1.0.0",
            description="x",
            author="a",
            skills=[PackSkillEntry(name="s", path="s")],
        )
        PackManifest(
            name="my-pack-123",
            version="1.0.0",
            description="x",
            author="a",
            skills=[PackSkillEntry(name="s", path="s")],
        )

        # Invalid: uppercase
        with pytest.raises(ValueError, match="must be lowercase"):
            PackManifest(
                name="MyPack",
                version="1.0.0",
                description="x",
                author="a",
                skills=[PackSkillEntry(name="s", path="s")],
            )

        # Invalid: starts with hyphen
        with pytest.raises(ValueError, match="must be lowercase"):
            PackManifest(
                name="-bad",
                version="1.0.0",
                description="x",
                author="a",
                skills=[PackSkillEntry(name="s", path="s")],
            )

        # Invalid: contains underscore
        with pytest.raises(ValueError, match="must be lowercase"):
            PackManifest(
                name="my_pack",
                version="1.0.0",
                description="x",
                author="a",
                skills=[PackSkillEntry(name="s", path="s")],
            )

    def test_version_must_be_semver(self) -> None:
        """Version must be MAJOR.MINOR.PATCH format."""
        # Valid
        PackManifest(
            name="ok",
            version="0.0.1",
            description="x",
            author="a",
            skills=[PackSkillEntry(name="s", path="s")],
        )

        # Invalid: not semver
        with pytest.raises(ValueError, match="must be valid semver"):
            PackManifest(
                name="bad",
                version="1.0",
                description="x",
                author="a",
                skills=[PackSkillEntry(name="s", path="s")],
            )

        with pytest.raises(ValueError, match="must be valid semver"):
            PackManifest(
                name="bad",
                version="v1.0.0",
                description="x",
                author="a",
                skills=[PackSkillEntry(name="s", path="s")],
            )

    def test_schema_version_must_be_1(self) -> None:
        """Only schema_version '1' is supported."""
        with pytest.raises(ValueError, match="Unsupported schema_version"):
            PackManifest(
                name="bad",
                version="1.0.0",
                description="x",
                author="a",
                schema_version="2",
                skills=[PackSkillEntry(name="s", path="s")],
            )

    def test_skills_list_cannot_be_empty(self) -> None:
        """At least one skill is required."""
        with pytest.raises(ValueError):
            PackManifest(
                name="bad",
                version="1.0.0",
                description="x",
                author="a",
                skills=[],
            )

    def test_duplicate_skill_names_rejected(self) -> None:
        """Skill names within a pack must be unique."""
        with pytest.raises(ValueError, match="Duplicate skill name"):
            PackManifest(
                name="bad",
                version="1.0.0",
                description="x",
                author="a",
                skills=[
                    PackSkillEntry(name="same", path="a"),
                    PackSkillEntry(name="same", path="b"),
                ],
            )

    def test_missing_required_field_name(self) -> None:
        with pytest.raises(ValueError):
            PackManifest(  # type: ignore[call-arg]
                version="1.0.0",
                description="x",
                author="a",
                skills=[PackSkillEntry(name="s", path="s")],
            )

    def test_missing_required_field_author(self) -> None:
        with pytest.raises(ValueError):
            PackManifest(  # type: ignore[call-arg]
                name="ok",
                version="1.0.0",
                description="x",
                skills=[PackSkillEntry(name="s", path="s")],
            )

    def test_description_max_length(self) -> None:
        """Description is capped at 500 characters."""
        with pytest.raises(ValueError):
            PackManifest(
                name="ok",
                version="1.0.0",
                description="x" * 501,
                author="a",
                skills=[PackSkillEntry(name="s", path="s")],
            )

    def test_serialization_roundtrip(self) -> None:
        manifest = PackManifest(
            name="test-pack",
            version="1.0.0",
            description="Test",
            author="tester",
            tags=["test"],
            skills=[PackSkillEntry(name="s", path="skills/s")],
        )
        data = manifest_to_dict(manifest)
        assert data["name"] == "test-pack"
        assert data["version"] == "1.0.0"
        assert "skills" in data
        assert len(data["skills"]) == 1

    def test_dependencies_parsing(self) -> None:
        manifest = PackManifest(
            name="dep-pack",
            version="1.0.0",
            description="Pack with deps",
            author="tester",
            skills=[PackSkillEntry(name="s", path="s")],
            dependencies={  # type: ignore[arg-type]
                "packs": [{"name": "base-utils", "version_constraint": "^1.0.0"}],
                "engine": {"min_version": "0.1.0"},
            },
        )
        assert len(manifest.dependencies.packs) == 1
        assert manifest.dependencies.packs[0].name == "base-utils"
        assert manifest.dependencies.packs[0].version_constraint == "^1.0.0"
        assert manifest.dependencies.engine["min_version"] == "0.1.0"

    def test_governance_defaults(self) -> None:
        manifest = PackManifest(
            name="gov-pack",
            version="1.0.0",
            description="Pack with governance",
            author="tester",
            skills=[PackSkillEntry(name="s", path="s")],
        )
        assert manifest.governance.min_autonomy_level == ""
        assert manifest.governance.approval_required_for == []
        assert manifest.governance.max_instructions_chars == 16000

    def test_governance_custom_values(self) -> None:
        manifest = PackManifest(
            name="gov-pack",
            version="1.0.0",
            description="Pack with custom governance",
            author="tester",
            skills=[PackSkillEntry(name="s", path="s")],
            governance={  # type: ignore[arg-type]
                "min_autonomy_level": "supervised",
                "approval_required_for": ["kubectl delete"],
                "max_instructions_chars": 32000,
            },
        )
        assert manifest.governance.min_autonomy_level == "supervised"
        assert manifest.governance.approval_required_for == ["kubectl delete"]
        assert manifest.governance.max_instructions_chars == 32000


class TestParsePackYaml:
    """Test PACK.yaml file parsing."""

    def test_parse_valid_yaml(self, tmp_path: Path) -> None:
        pack_yaml = tmp_path / "PACK.yaml"
        pack_yaml.write_text(
            textwrap.dedent("""\
            schema_version: "1"
            name: test-pack
            version: 1.0.0
            description: A test pack
            author: tester
            skills:
              - name: my-skill
                path: skills/my-skill
            """),
            encoding="utf-8",
        )
        manifest = parse_pack_yaml(pack_yaml)
        assert manifest.name == "test-pack"
        assert manifest.version == "1.0.0"

    def test_parse_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="PACK.yaml not found"):
            parse_pack_yaml(tmp_path / "PACK.yaml")

    def test_parse_invalid_yaml(self, tmp_path: Path) -> None:
        pack_yaml = tmp_path / "PACK.yaml"
        pack_yaml.write_text(": : invalid yaml content [", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid YAML"):
            parse_pack_yaml(pack_yaml)

    def test_parse_non_mapping_yaml(self, tmp_path: Path) -> None:
        pack_yaml = tmp_path / "PACK.yaml"
        pack_yaml.write_text("- list\n- not mapping\n", encoding="utf-8")
        with pytest.raises(ValueError, match="must be a YAML mapping"):
            parse_pack_yaml(pack_yaml)
