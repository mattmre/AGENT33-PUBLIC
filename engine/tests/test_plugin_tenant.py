"""Tests for multi-tenant plugin configuration and visibility rules."""

from __future__ import annotations

from unittest.mock import MagicMock

from agent33.plugins.manifest import PluginManifest
from agent33.plugins.tenant import (
    TenantPluginConfig,
    TenantPluginState,
    get_visible_plugins,
)


def _make_manifest(name: str, **kwargs) -> PluginManifest:
    return PluginManifest(name=name, version="1.0.0", **kwargs)


class TestTenantPluginConfig:
    """Tests for TenantPluginConfig model."""

    def test_default_enabled(self) -> None:
        config = TenantPluginConfig(tenant_id="t1", plugin_name="my-plugin")
        assert config.enabled is True
        assert config.config_overrides == {}
        assert config.permission_overrides == {}

    def test_with_overrides(self) -> None:
        config = TenantPluginConfig(
            tenant_id="t1",
            plugin_name="my-plugin",
            enabled=False,
            config_overrides={"max_replicas": 5},
            permission_overrides={"file:write": False},
        )
        assert config.enabled is False
        assert config.config_overrides["max_replicas"] == 5
        assert config.permission_overrides["file:write"] is False


class TestTenantPluginState:
    """Tests for TenantPluginState model."""

    def test_defaults(self) -> None:
        state = TenantPluginState(tenant_id="t1", plugin_name="my-plugin")
        assert state.is_enabled is True
        assert state.custom_config == {}

    def test_with_custom_config(self) -> None:
        state = TenantPluginState(
            tenant_id="t1",
            plugin_name="my-plugin",
            is_enabled=False,
            custom_config={"key": "value"},
        )
        assert state.is_enabled is False
        assert state.custom_config["key"] == "value"


class TestGetVisiblePlugins:
    """Tests for get_visible_plugins() visibility rules."""

    def _make_registry(self, plugins: dict) -> MagicMock:
        """Create a mock registry with given plugins.

        plugins: dict of {name: scope}
        """
        mock_reg = MagicMock()
        manifests = []
        entries = {}
        for name, scope in plugins.items():
            manifest = _make_manifest(name)
            manifests.append(manifest)
            entry = MagicMock()
            entry.manifest = MagicMock()
            entry.manifest.name = name
            entry.manifest.scope = scope
            entries[name] = entry

        mock_reg.list_all.return_value = manifests
        mock_reg.get.side_effect = lambda n: entries.get(n)
        return mock_reg

    def test_system_plugins_always_visible(self) -> None:
        registry = self._make_registry({"core-plugin": "system"})
        visible = get_visible_plugins("tenant-1", registry, {})
        assert len(visible) == 1
        assert visible[0].name == "core-plugin"

    def test_shared_plugins_visible_by_default(self) -> None:
        registry = self._make_registry({"shared-plugin": "shared"})
        visible = get_visible_plugins("tenant-1", registry, {})
        assert len(visible) == 1

    def test_shared_plugins_hidden_when_disabled(self) -> None:
        registry = self._make_registry({"shared-plugin": "shared"})
        configs = {
            "tenant-1:shared-plugin": TenantPluginConfig(
                tenant_id="tenant-1",
                plugin_name="shared-plugin",
                enabled=False,
            ),
        }
        visible = get_visible_plugins("tenant-1", registry, configs)
        assert len(visible) == 0

    def test_tenant_plugins_hidden_without_config(self) -> None:
        registry = self._make_registry({"tenant-plugin": "tenant"})
        visible = get_visible_plugins("tenant-1", registry, {})
        assert len(visible) == 0

    def test_tenant_plugins_visible_when_configured(self) -> None:
        registry = self._make_registry({"tenant-plugin": "tenant"})
        configs = {
            "tenant-1:tenant-plugin": TenantPluginConfig(
                tenant_id="tenant-1",
                plugin_name="tenant-plugin",
                enabled=True,
            ),
        }
        visible = get_visible_plugins("tenant-1", registry, configs)
        assert len(visible) == 1

    def test_tenant_plugins_hidden_for_other_tenants(self) -> None:
        registry = self._make_registry({"tenant-plugin": "tenant"})
        configs = {
            "tenant-1:tenant-plugin": TenantPluginConfig(
                tenant_id="tenant-1",
                plugin_name="tenant-plugin",
                enabled=True,
            ),
        }
        # tenant-2 has no config for this plugin
        visible = get_visible_plugins("tenant-2", registry, configs)
        assert len(visible) == 0

    def test_mixed_scopes(self) -> None:
        registry = self._make_registry(
            {
                "sys-plugin": "system",
                "shared-plugin": "shared",
                "tenant-plugin": "tenant",
            }
        )
        configs = {
            "tenant-1:tenant-plugin": TenantPluginConfig(
                tenant_id="tenant-1",
                plugin_name="tenant-plugin",
                enabled=True,
            ),
        }
        visible = get_visible_plugins("tenant-1", registry, configs)
        # System (always), shared (default enabled), tenant (configured)
        assert len(visible) == 3

    def test_disabled_tenant_plugin_not_visible(self) -> None:
        registry = self._make_registry({"tenant-plugin": "tenant"})
        configs = {
            "tenant-1:tenant-plugin": TenantPluginConfig(
                tenant_id="tenant-1",
                plugin_name="tenant-plugin",
                enabled=False,
            ),
        }
        visible = get_visible_plugins("tenant-1", registry, configs)
        assert len(visible) == 0
