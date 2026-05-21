"""Tests for PluginBase abstract class lifecycle and contribution helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent33.plugins.base import PluginBase
from agent33.plugins.context import PluginContext
from agent33.plugins.manifest import (
    PluginContributions,
    PluginManifest,
    PluginPermission,
)
from agent33.skills.definition import SkillDefinition


def _make_manifest(**overrides: Any) -> PluginManifest:
    """Create a manifest with defaults."""
    defaults: dict[str, Any] = {
        "name": "test-plugin",
        "version": "1.0.0",
        "entry_point": "plugin:Plugin",
        "contributions": PluginContributions(),
        "permissions": [],
    }
    defaults.update(overrides)
    return PluginManifest(**defaults)


def _make_context(
    plugin_name: str = "test-plugin",
    skill_registry: Any = None,
    tool_registry: Any = None,
    hook_registry: Any = None,
    granted_permissions: frozenset[str] | None = None,
) -> PluginContext:
    """Create a PluginContext with mock registries."""
    return PluginContext(
        plugin_name=plugin_name,
        plugin_dir=Path("/tmp/test-plugin"),
        granted_permissions=granted_permissions or frozenset(),
        skill_registry=skill_registry or MagicMock(),
        tool_registry=tool_registry or MagicMock(),
        hook_registry=hook_registry,
    )


class ConcretePlugin(PluginBase):
    """Concrete implementation for testing."""

    def __init__(self, manifest: PluginManifest, context: PluginContext) -> None:
        super().__init__(manifest, context)
        self.loaded = False
        self.enabled = False
        self.disabled = False
        self.unloaded = False

    async def on_load(self) -> None:
        self.loaded = True

    async def on_enable(self) -> None:
        self.enabled = True

    async def on_disable(self) -> None:
        self.disabled = True

    async def on_unload(self) -> None:
        self.unloaded = True


class TestPluginBaseProperties:
    """Tests for PluginBase property accessors."""

    def test_name_property(self) -> None:
        manifest = _make_manifest(name="my-plugin")
        ctx = _make_context(plugin_name="my-plugin")
        plugin = ConcretePlugin(manifest, ctx)
        assert plugin.name == "my-plugin"

    def test_version_property(self) -> None:
        manifest = _make_manifest(version="2.3.4")
        ctx = _make_context()
        plugin = ConcretePlugin(manifest, ctx)
        assert plugin.version == "2.3.4"

    def test_manifest_property(self) -> None:
        manifest = _make_manifest()
        ctx = _make_context()
        plugin = ConcretePlugin(manifest, ctx)
        assert plugin.manifest is manifest

    def test_context_property(self) -> None:
        manifest = _make_manifest()
        ctx = _make_context()
        plugin = ConcretePlugin(manifest, ctx)
        assert plugin.context is ctx


class TestPluginBaseLifecycle:
    """Tests for PluginBase lifecycle methods."""

    async def test_on_load_called(self) -> None:
        plugin = ConcretePlugin(_make_manifest(), _make_context())
        await plugin.on_load()
        assert plugin.loaded is True

    async def test_on_enable_called(self) -> None:
        plugin = ConcretePlugin(_make_manifest(), _make_context())
        await plugin.on_enable()
        assert plugin.enabled is True

    async def test_on_disable_called(self) -> None:
        plugin = ConcretePlugin(_make_manifest(), _make_context())
        await plugin.on_disable()
        assert plugin.disabled is True

    async def test_on_unload_called(self) -> None:
        plugin = ConcretePlugin(_make_manifest(), _make_context())
        await plugin.on_unload()
        assert plugin.unloaded is True


class TestRegisterSkill:
    """Tests for PluginBase.register_skill() contribution helper."""

    def test_register_declared_skill(self) -> None:
        mock_registry = MagicMock()
        manifest = _make_manifest(
            contributions=PluginContributions(skills=["my-skill"]),
        )
        ctx = _make_context(skill_registry=mock_registry)
        plugin = ConcretePlugin(manifest, ctx)

        skill = SkillDefinition(name="my-skill", description="Test skill")
        plugin.register_skill(skill)

        mock_registry.register.assert_called_once_with(skill)

    def test_register_undeclared_skill_raises(self) -> None:
        manifest = _make_manifest(
            contributions=PluginContributions(skills=["declared-skill"]),
        )
        ctx = _make_context()
        plugin = ConcretePlugin(manifest, ctx)

        skill = SkillDefinition(name="undeclared-skill", description="Test")
        with pytest.raises(ValueError, match="undeclared skill"):
            plugin.register_skill(skill)

    def test_register_non_skill_raises_type_error(self) -> None:
        manifest = _make_manifest()
        ctx = _make_context()
        plugin = ConcretePlugin(manifest, ctx)

        with pytest.raises(TypeError, match="Expected SkillDefinition"):
            plugin.register_skill("not a skill")


class TestRegisterTool:
    """Tests for PluginBase.register_tool() contribution helper."""

    def test_register_undeclared_tool_raises(self) -> None:
        """Registering a tool whose class name is not in contributions raises ValueError."""
        manifest = _make_manifest(
            contributions=PluginContributions(tools=["DeclaredTool"]),
        )
        ctx = _make_context()
        plugin = ConcretePlugin(manifest, ctx)

        # MagicMock satisfies the Tool protocol (has name/description).
        # So it passes the isinstance check but fails the undeclared check.
        mock_tool = MagicMock()
        type(mock_tool).__name__ = "UndeclaredTool"
        with pytest.raises(ValueError, match="undeclared tool"):
            plugin.register_tool(mock_tool)

    def test_register_non_tool_raises_type_error(self) -> None:
        manifest = _make_manifest()
        ctx = _make_context()
        plugin = ConcretePlugin(manifest, ctx)

        with pytest.raises(TypeError, match="Expected Tool"):
            plugin.register_tool("not a tool")


class TestRegisterHook:
    """Tests for PluginBase.register_hook() contribution helper."""

    def test_register_hook_without_permission_raises(self) -> None:
        manifest = _make_manifest(permissions=[])  # No hook:register
        ctx = _make_context()
        plugin = ConcretePlugin(manifest, ctx)

        with pytest.raises(PermissionError, match="hook:register"):
            plugin.register_hook(MagicMock())

    def test_register_hook_without_registry_raises(self) -> None:
        manifest = _make_manifest(
            permissions=[PluginPermission.HOOK_REGISTER],
            contributions=PluginContributions(hooks=["MyHook"]),
        )
        ctx = _make_context(hook_registry=None)  # No H01
        plugin = ConcretePlugin(manifest, ctx)

        mock_hook = MagicMock()
        mock_hook.__class__.__name__ = "MyHook"
        type(mock_hook).__name__ = "MyHook"
        with pytest.raises(RuntimeError, match="hook_registry"):
            plugin.register_hook(mock_hook)

    def test_register_undeclared_hook_raises(self) -> None:
        manifest = _make_manifest(
            permissions=[PluginPermission.HOOK_REGISTER],
            contributions=PluginContributions(hooks=["DeclaredHook"]),
        )
        mock_hook_registry = MagicMock()
        ctx = _make_context(hook_registry=mock_hook_registry)
        plugin = ConcretePlugin(manifest, ctx)

        mock_hook = MagicMock()
        mock_hook.__class__.__name__ = "UndeclaredHook"
        type(mock_hook).__name__ = "UndeclaredHook"
        with pytest.raises(ValueError, match="undeclared hook"):
            plugin.register_hook(mock_hook)

    def test_register_declared_hook_succeeds(self) -> None:
        manifest = _make_manifest(
            permissions=[PluginPermission.HOOK_REGISTER],
            contributions=PluginContributions(hooks=["MyHook"]),
        )
        mock_hook_registry = MagicMock()
        ctx = _make_context(hook_registry=mock_hook_registry)
        plugin = ConcretePlugin(manifest, ctx)

        mock_hook = MagicMock()
        type(mock_hook).__name__ = "MyHook"
        plugin.register_hook(mock_hook, priority=5)

        mock_hook_registry.register.assert_called_once_with(
            mock_hook, priority=5, source="test-plugin"
        )
