"""End-to-end integration tests for the plugin lifecycle.

These tests exercise the full discovery -> load -> enable -> invoke -> disable -> unload
pipeline using real filesystem operations and actual plugin module loading.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from agent33.plugins.capabilities import CapabilityGrant
from agent33.plugins.context import PluginContext
from agent33.plugins.models import PluginState
from agent33.plugins.registry import (
    CyclicDependencyError,
    PluginRegistry,
)
from agent33.plugins.scoped import ScopedSkillRegistry, ScopedToolRegistry
from agent33.skills.registry import SkillRegistry

if TYPE_CHECKING:
    from pathlib import Path

    from agent33.plugins.manifest import PluginManifest


def _write_plugin(
    base_dir: Path,
    name: str,
    version: str = "1.0.0",
    *,
    yaml_extra: str = "",
    plugin_code: str = "",
) -> Path:
    """Write a complete plugin directory with manifest and module."""
    plugin_dir = base_dir / name
    plugin_dir.mkdir(parents=True, exist_ok=True)

    yaml_content = f"""\
name: {name}
version: {version}
description: Test plugin {name}
entry_point: "plugin:Plugin"
{yaml_extra}
"""
    (plugin_dir / "plugin.yaml").write_text(yaml_content, encoding="utf-8")

    if not plugin_code:
        plugin_code = """\
from agent33.plugins.base import PluginBase

class Plugin(PluginBase):
    async def on_load(self):
        self._logger.info("on_load called")

    async def on_enable(self):
        self._logger.info("on_enable called")

    async def on_disable(self):
        self._logger.info("on_disable called")

    async def on_unload(self):
        self._logger.info("on_unload called")
"""
    (plugin_dir / "plugin.py").write_text(plugin_code, encoding="utf-8")
    return plugin_dir


def _make_context_factory(
    skill_registry: SkillRegistry | None = None,
) -> Any:
    """Create a context factory for integration tests."""
    _skill_reg = skill_registry or SkillRegistry()
    _tool_reg = MagicMock()

    def factory(manifest: PluginManifest, plugin_dir: Path) -> PluginContext:
        grants = CapabilityGrant(
            manifest_permissions=[p.value for p in manifest.permissions],
        )
        return PluginContext(
            plugin_name=manifest.name,
            plugin_dir=plugin_dir,
            granted_permissions=grants.effective_permissions,
            skill_registry=ScopedSkillRegistry(_skill_reg, grants),
            tool_registry=ScopedToolRegistry(_tool_reg, grants),
            hook_registry=None,
        )

    return factory


class TestFullPluginLifecycle:
    """End-to-end lifecycle: discover -> load -> enable -> disable -> unload."""

    async def test_complete_lifecycle(self, tmp_path) -> None:
        """Walk through the full plugin lifecycle."""
        _write_plugin(tmp_path, "lifecycle-test")

        registry = PluginRegistry()

        # Discover
        count = registry.discover(tmp_path)
        assert count == 1
        assert registry.get_state("lifecycle-test") == PluginState.DISCOVERED

        # Load
        await registry.load("lifecycle-test", _make_context_factory())
        assert registry.get_state("lifecycle-test") == PluginState.LOADED
        entry = registry.get("lifecycle-test")
        assert entry is not None
        assert entry.instance is not None

        # Enable
        await registry.enable("lifecycle-test")
        assert registry.get_state("lifecycle-test") == PluginState.ACTIVE
        assert registry.active_count == 1

        # Disable
        await registry.disable("lifecycle-test")
        assert registry.get_state("lifecycle-test") == PluginState.DISABLED
        assert registry.active_count == 0

        # Re-enable
        await registry.enable("lifecycle-test")
        assert registry.get_state("lifecycle-test") == PluginState.ACTIVE

        # Unload (auto-disables first)
        await registry.unload("lifecycle-test")
        assert registry.get_state("lifecycle-test") == PluginState.UNLOADED
        entry = registry.get("lifecycle-test")
        assert entry is not None
        assert entry.instance is None

    async def test_unload_all_in_reverse_order(self, tmp_path) -> None:
        """unload_all() should unload in reverse dependency order."""
        _write_plugin(tmp_path, "base-plugin", yaml_extra="")
        _write_plugin(
            tmp_path,
            "dependent-plugin",
            yaml_extra="dependencies:\n  - name: base-plugin\n",
        )

        registry = PluginRegistry()
        registry.discover(tmp_path)
        await registry.load_all(_make_context_factory())

        # Enable both
        await registry.enable("base-plugin")
        await registry.enable("dependent-plugin")
        assert registry.active_count == 2

        # Unload all
        await registry.unload_all()
        assert registry.active_count == 0
        assert registry.get_state("base-plugin") == PluginState.UNLOADED
        assert registry.get_state("dependent-plugin") == PluginState.UNLOADED


class TestPluginWithSkillRegistration:
    """Tests for plugins that register skills during lifecycle."""

    async def test_plugin_registers_skill_on_load(self, tmp_path) -> None:
        """Plugin can register skills during on_load()."""
        _write_plugin(
            tmp_path,
            "skill-plugin",
            yaml_extra="""\
contributions:
  skills:
    - test-skill
permissions:
  - config:read
""",
            plugin_code="""\
from agent33.plugins.base import PluginBase
from agent33.skills.definition import SkillDefinition

class Plugin(PluginBase):
    async def on_load(self):
        skill = SkillDefinition(
            name="test-skill",
            version=self.version,
            description="A skill from a plugin",
        )
        self.register_skill(skill)
""",
        )

        skill_registry = SkillRegistry()
        registry = PluginRegistry()
        registry.discover(tmp_path)
        await registry.load("skill-plugin", _make_context_factory(skill_registry))

        # Verify the skill was registered
        skill = skill_registry.get("test-skill")
        assert skill is not None
        assert skill.name == "test-skill"
        assert skill.description == "A skill from a plugin"

    async def test_plugin_cannot_register_undeclared_skill(self, tmp_path) -> None:
        """Plugin cannot register a skill not declared in its manifest."""
        _write_plugin(
            tmp_path,
            "sneaky-plugin",
            yaml_extra="""\
contributions:
  skills:
    - declared-skill
""",
            plugin_code="""\
from agent33.plugins.base import PluginBase
from agent33.skills.definition import SkillDefinition

class Plugin(PluginBase):
    async def on_load(self):
        skill = SkillDefinition(
            name="undeclared-skill",
            description="Sneaky",
        )
        self.register_skill(skill)
""",
        )

        registry = PluginRegistry()
        registry.discover(tmp_path)
        with pytest.raises(ValueError, match="undeclared skill"):
            await registry.load("sneaky-plugin", _make_context_factory())

        # Plugin should be in ERROR state
        assert registry.get_state("sneaky-plugin") == PluginState.ERROR


class TestPluginDependencyChain:
    """Tests for dependency resolution in integration context."""

    async def test_load_all_respects_dependency_order(self, tmp_path) -> None:
        """load_all() loads in topological order."""
        _write_plugin(
            tmp_path,
            "foundation",
            plugin_code="""\
from agent33.plugins.base import PluginBase

class Plugin(PluginBase):
    async def on_load(self):
        pass  # loaded first
""",
        )
        _write_plugin(
            tmp_path,
            "middleware",
            yaml_extra="dependencies:\n  - name: foundation\n",
            plugin_code="""\
from agent33.plugins.base import PluginBase

class Plugin(PluginBase):
    async def on_load(self):
        pass  # loaded second
""",
        )
        _write_plugin(
            tmp_path,
            "application",
            yaml_extra="dependencies:\n  - name: middleware\n",
            plugin_code="""\
from agent33.plugins.base import PluginBase

class Plugin(PluginBase):
    async def on_load(self):
        pass  # loaded third
""",
        )

        registry = PluginRegistry()
        registry.discover(tmp_path)
        loaded = await registry.load_all(_make_context_factory())
        assert loaded == 3

        # Verify dependency order
        order = registry.resolve_load_order()
        assert order.index("foundation") < order.index("middleware")
        assert order.index("middleware") < order.index("application")

    async def test_cyclic_deps_prevent_loading(self, tmp_path) -> None:
        """Cyclic dependencies prevent load_all() from succeeding."""
        _write_plugin(
            tmp_path,
            "plugin-x",
            yaml_extra="dependencies:\n  - name: plugin-y\n",
        )
        _write_plugin(
            tmp_path,
            "plugin-y",
            yaml_extra="dependencies:\n  - name: plugin-x\n",
        )

        registry = PluginRegistry()
        registry.discover(tmp_path)
        with pytest.raises(CyclicDependencyError):
            await registry.load_all(_make_context_factory())


class TestPluginVersionConstraintIntegration:
    """Tests for version constraint checking with real manifests."""

    def test_version_constraint_satisfied(self, tmp_path) -> None:
        _write_plugin(tmp_path, "provider", version="2.0.0")
        _write_plugin(
            tmp_path,
            "consumer",
            yaml_extra='dependencies:\n  - name: provider\n    version_constraint: ">=1.0.0"\n',
        )

        registry = PluginRegistry()
        registry.discover(tmp_path)
        violations = registry.check_version_constraints()
        assert violations == []

    def test_version_constraint_violated(self, tmp_path) -> None:
        _write_plugin(tmp_path, "provider", version="0.5.0")
        _write_plugin(
            tmp_path,
            "consumer",
            yaml_extra='dependencies:\n  - name: provider\n    version_constraint: ">=1.0.0"\n',
        )

        registry = PluginRegistry()
        registry.discover(tmp_path)
        violations = registry.check_version_constraints()
        assert len(violations) == 1
        assert ">=1.0.0" in violations[0]


class TestCapabilityGrantIntegration:
    """Tests for capability grants working with the context factory."""

    async def test_plugin_receives_granted_permissions(self, tmp_path) -> None:
        _write_plugin(
            tmp_path,
            "permissioned-plugin",
            yaml_extra="""\
permissions:
  - file:read
  - config:read
""",
            plugin_code="""\
from agent33.plugins.base import PluginBase

class Plugin(PluginBase):
    async def on_load(self):
        # Verify context has permissions
        assert self.context.has_permission("file:read")
        assert self.context.has_permission("config:read")
""",
        )

        registry = PluginRegistry()
        registry.discover(tmp_path)
        await registry.load("permissioned-plugin", _make_context_factory())
        assert registry.get_state("permissioned-plugin") == PluginState.LOADED


class TestPluginErrorHandling:
    """Tests for graceful error handling during plugin lifecycle."""

    async def test_on_load_error_sets_error_state(self, tmp_path) -> None:
        _write_plugin(
            tmp_path,
            "broken-plugin",
            plugin_code="""\
from agent33.plugins.base import PluginBase

class Plugin(PluginBase):
    async def on_load(self):
        raise RuntimeError("broken on load")
""",
        )

        registry = PluginRegistry()
        registry.discover(tmp_path)
        with pytest.raises(RuntimeError, match="broken on load"):
            await registry.load("broken-plugin", _make_context_factory())

        assert registry.get_state("broken-plugin") == PluginState.ERROR
        entry = registry.get("broken-plugin")
        assert entry is not None
        assert "broken on load" in entry.error

    async def test_on_enable_error_sets_error_state(self, tmp_path) -> None:
        _write_plugin(
            tmp_path,
            "enable-fail-plugin",
            plugin_code="""\
from agent33.plugins.base import PluginBase

class Plugin(PluginBase):
    async def on_load(self):
        pass

    async def on_enable(self):
        raise RuntimeError("broken on enable")
""",
        )

        registry = PluginRegistry()
        registry.discover(tmp_path)
        await registry.load("enable-fail-plugin", _make_context_factory())
        with pytest.raises(RuntimeError, match="broken on enable"):
            await registry.enable("enable-fail-plugin")

        assert registry.get_state("enable-fail-plugin") == PluginState.ERROR

    async def test_on_disable_error_is_logged_not_raised(self, tmp_path) -> None:
        """Errors during on_disable() are logged but do not prevent disabling."""
        _write_plugin(
            tmp_path,
            "disable-fail-plugin",
            plugin_code="""\
from agent33.plugins.base import PluginBase

class Plugin(PluginBase):
    async def on_load(self):
        pass

    async def on_enable(self):
        pass

    async def on_disable(self):
        raise RuntimeError("broken on disable")
""",
        )

        registry = PluginRegistry()
        registry.discover(tmp_path)
        await registry.load("disable-fail-plugin", _make_context_factory())
        await registry.enable("disable-fail-plugin")

        # disable should succeed despite the error in on_disable
        await registry.disable("disable-fail-plugin")
        assert registry.get_state("disable-fail-plugin") == PluginState.DISABLED

    async def test_on_unload_error_is_logged_not_raised(self, tmp_path) -> None:
        """Errors during on_unload() are logged but do not prevent unloading."""
        _write_plugin(
            tmp_path,
            "unload-fail-plugin",
            plugin_code="""\
from agent33.plugins.base import PluginBase

class Plugin(PluginBase):
    async def on_load(self):
        pass

    async def on_enable(self):
        pass

    async def on_disable(self):
        pass

    async def on_unload(self):
        raise RuntimeError("broken on unload")
""",
        )

        registry = PluginRegistry()
        registry.discover(tmp_path)
        await registry.load("unload-fail-plugin", _make_context_factory())
        await registry.enable("unload-fail-plugin")

        # unload should succeed despite the error
        await registry.unload("unload-fail-plugin")
        assert registry.get_state("unload-fail-plugin") == PluginState.UNLOADED


class TestPluginRemoveAfterUnload:
    """Tests for removing plugins after unloading."""

    async def test_remove_after_unload(self, tmp_path) -> None:
        _write_plugin(tmp_path, "removable-plugin")
        registry = PluginRegistry()
        registry.discover(tmp_path)
        await registry.load("removable-plugin", _make_context_factory())
        await registry.enable("removable-plugin")
        await registry.unload("removable-plugin")

        result = registry.remove("removable-plugin")
        assert result is True
        assert registry.count == 0
        assert registry.get("removable-plugin") is None
