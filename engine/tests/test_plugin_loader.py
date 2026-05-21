"""Tests for plugin manifest file parsing (YAML, TOML, Markdown frontmatter)."""

from __future__ import annotations

import pytest

from agent33.plugins.loader import load_manifest
from agent33.plugins.manifest import PluginManifest


@pytest.fixture()
def yaml_plugin_dir(tmp_path):
    """Create a plugin directory with a YAML manifest."""
    plugin_dir = tmp_path / "test-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.yaml").write_text(
        """\
name: test-plugin
version: 1.0.0
description: A test plugin
author: test-team
entry_point: "plugin:TestPlugin"

contributions:
  skills:
    - test-skill
  tools:
    - TestTool

permissions:
  - file:read
  - config:read

tags:
  - testing
  - example
""",
        encoding="utf-8",
    )
    return plugin_dir


@pytest.fixture()
def yml_plugin_dir(tmp_path):
    """Create a plugin directory with a .yml manifest."""
    plugin_dir = tmp_path / "yml-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.yml").write_text(
        """\
name: yml-plugin
version: 2.0.0
description: Plugin with .yml extension
""",
        encoding="utf-8",
    )
    return plugin_dir


@pytest.fixture()
def toml_plugin_dir(tmp_path):
    """Create a plugin directory with a TOML manifest."""
    plugin_dir = tmp_path / "toml-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.toml").write_text(
        """\
[plugin]
name = "toml-plugin"
version = "1.0.0"
description = "A TOML-based plugin"
author = "toml-team"

[plugin.contributions]
skills = ["toml-skill"]

[[plugin.dependencies]]
name = "core"
version_constraint = ">=1.0.0"
""",
        encoding="utf-8",
    )
    return plugin_dir


@pytest.fixture()
def md_plugin_dir(tmp_path):
    """Create a plugin directory with a PLUGIN.md manifest."""
    plugin_dir = tmp_path / "md-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "PLUGIN.md").write_text(
        """\
---
name: md-plugin
version: 1.0.0
author: md-team
tags:
  - markdown
---
This is a plugin described in Markdown format.
It supports rich descriptions in the body.
""",
        encoding="utf-8",
    )
    return plugin_dir


class TestYAMLManifestLoading:
    """Tests for YAML manifest parsing."""

    def test_load_yaml_manifest(self, yaml_plugin_dir) -> None:
        manifest = load_manifest(yaml_plugin_dir)
        assert isinstance(manifest, PluginManifest)
        assert manifest.name == "test-plugin"
        assert manifest.version == "1.0.0"
        assert manifest.description == "A test plugin"
        assert manifest.author == "test-team"
        assert manifest.entry_point == "plugin:TestPlugin"
        assert "test-skill" in manifest.contributions.skills
        assert "TestTool" in manifest.contributions.tools
        assert len(manifest.permissions) == 2
        assert "testing" in manifest.tags

    def test_load_yml_extension(self, yml_plugin_dir) -> None:
        manifest = load_manifest(yml_plugin_dir)
        assert manifest.name == "yml-plugin"
        assert manifest.version == "2.0.0"


class TestTOMLManifestLoading:
    """Tests for TOML manifest parsing."""

    def test_load_toml_manifest(self, toml_plugin_dir) -> None:
        manifest = load_manifest(toml_plugin_dir)
        assert manifest.name == "toml-plugin"
        assert manifest.version == "1.0.0"
        assert manifest.description == "A TOML-based plugin"
        assert "toml-skill" in manifest.contributions.skills
        assert len(manifest.dependencies) == 1
        assert manifest.dependencies[0].name == "core"
        assert manifest.dependencies[0].version_constraint == ">=1.0.0"

    def test_load_toml_without_plugin_section(self, tmp_path) -> None:
        """TOML without [plugin] section uses root keys."""
        plugin_dir = tmp_path / "flat-toml"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.toml").write_text(
            'name = "flat-toml"\nversion = "1.0.0"\n',
            encoding="utf-8",
        )
        manifest = load_manifest(plugin_dir)
        assert manifest.name == "flat-toml"


class TestMarkdownManifestLoading:
    """Tests for PLUGIN.md frontmatter parsing."""

    def test_load_md_manifest(self, md_plugin_dir) -> None:
        manifest = load_manifest(md_plugin_dir)
        assert manifest.name == "md-plugin"
        assert manifest.version == "1.0.0"
        assert manifest.author == "md-team"
        assert "markdown" in manifest.tags
        # Body becomes description when no explicit description
        assert "Markdown format" in manifest.description


class TestManifestNotFound:
    """Tests for error handling when no manifest exists."""

    def test_no_manifest_raises_file_not_found(self, tmp_path) -> None:
        plugin_dir = tmp_path / "empty-plugin"
        plugin_dir.mkdir()
        with pytest.raises(FileNotFoundError, match="No plugin manifest found"):
            load_manifest(plugin_dir)


class TestManifestPriorityOrder:
    """Tests for manifest format priority (YAML > TOML > MD)."""

    def test_yaml_takes_priority_over_toml(self, tmp_path) -> None:
        plugin_dir = tmp_path / "priority-plugin"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.yaml").write_text(
            "name: from-yaml\nversion: 1.0.0\n", encoding="utf-8"
        )
        (plugin_dir / "plugin.toml").write_text(
            'name = "from-toml"\nversion = "1.0.0"\n', encoding="utf-8"
        )
        manifest = load_manifest(plugin_dir)
        assert manifest.name == "from-yaml"

    def test_toml_takes_priority_over_md(self, tmp_path) -> None:
        plugin_dir = tmp_path / "priority-plugin"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.toml").write_text(
            'name = "from-toml"\nversion = "1.0.0"\n', encoding="utf-8"
        )
        (plugin_dir / "PLUGIN.md").write_text(
            "---\nname: from-md\nversion: 1.0.0\n---\nBody\n", encoding="utf-8"
        )
        manifest = load_manifest(plugin_dir)
        assert manifest.name == "from-toml"


class TestManifestValidationErrors:
    """Tests for manifest validation errors during loading."""

    def test_invalid_yaml_content_raises(self, tmp_path) -> None:
        plugin_dir = tmp_path / "bad-yaml"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.yaml").write_text("not a mapping\n", encoding="utf-8")
        with pytest.raises(ValueError, match="must be a mapping"):
            load_manifest(plugin_dir)

    def test_missing_required_fields_raises(self, tmp_path) -> None:
        plugin_dir = tmp_path / "incomplete"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.yaml").write_text(
            "description: no name or version\n", encoding="utf-8"
        )
        with pytest.raises(ValueError):
            load_manifest(plugin_dir)
