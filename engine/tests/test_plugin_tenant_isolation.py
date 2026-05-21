"""Tests for tenant isolation hardening in PluginRegistry (Phase 32)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from agent33.plugins.context import PluginContext
from agent33.plugins.models import PluginState
from agent33.plugins.registry import PluginRegistry

if TYPE_CHECKING:
    from pathlib import Path

    from agent33.plugins.manifest import PluginManifest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_yaml_manifest(plugin_dir: Path, name: str, **kwargs: Any) -> None:
    """Write a minimal plugin.yaml manifest."""
    plugin_dir.mkdir(parents=True, exist_ok=True)
    yaml_content = f"name: {name}\nversion: {kwargs.get('version', '1.0.0')}\n"
    if "description" in kwargs:
        yaml_content += f"description: {kwargs['description']}\n"
    (plugin_dir / "plugin.yaml").write_text(yaml_content, encoding="utf-8")


def _write_plugin_module(plugin_dir: Path) -> None:
    """Write a minimal plugin.py module for loading."""
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.py").write_text(
        "from agent33.plugins.base import PluginBase\n\n"
        "class Plugin(PluginBase):\n"
        "    async def on_load(self): pass\n"
        "    async def on_enable(self): pass\n"
        "    async def on_disable(self): pass\n"
        "    async def on_unload(self): pass\n",
        encoding="utf-8",
    )


def _make_context_factory() -> Any:
    def factory(manifest: PluginManifest, plugin_dir: Path) -> PluginContext:
        return PluginContext(
            plugin_name=manifest.name,
            plugin_dir=plugin_dir,
            granted_permissions=frozenset(),
            skill_registry=MagicMock(),
            tool_registry=MagicMock(),
        )

    return factory


# ---------------------------------------------------------------------------
# PluginEntry tenant_id field
# ---------------------------------------------------------------------------


class TestPluginEntryTenantId:
    def test_entry_has_tenant_id_default_empty(self, tmp_path: Path) -> None:
        _write_yaml_manifest(tmp_path / "p1", "p1")
        reg = PluginRegistry()
        reg.discover(tmp_path)
        entry = reg.get("p1")
        assert entry is not None
        assert entry.tenant_id == ""

    async def test_entry_tenant_id_set_on_load(self, tmp_path: Path) -> None:
        _write_yaml_manifest(tmp_path / "p1", "p1")
        _write_plugin_module(tmp_path / "p1")
        reg = PluginRegistry()
        reg.discover(tmp_path)
        await reg.load("p1", _make_context_factory(), tenant_id="acme")
        entry = reg.get("p1")
        assert entry is not None
        assert entry.tenant_id == "acme"


# ---------------------------------------------------------------------------
# list_all tenant filtering
# ---------------------------------------------------------------------------


class TestListAllTenantFiltering:
    def test_list_all_without_tenant_returns_all(self, tmp_path: Path) -> None:
        _write_yaml_manifest(tmp_path / "sys-plugin", "sys-plugin")
        _write_yaml_manifest(tmp_path / "acme-plugin", "acme-plugin")
        _write_yaml_manifest(tmp_path / "other-plugin", "other-plugin")

        reg = PluginRegistry()
        reg.discover(tmp_path)
        # Set tenants
        reg._plugins["acme-plugin"].tenant_id = "acme"  # noqa: SLF001
        reg._plugins["other-plugin"].tenant_id = "other"  # noqa: SLF001

        all_plugins = reg.list_all()
        assert len(all_plugins) == 3

    def test_list_all_filtered_shows_system_and_own(self, tmp_path: Path) -> None:
        _write_yaml_manifest(tmp_path / "sys-plugin", "sys-plugin")
        _write_yaml_manifest(tmp_path / "acme-plugin", "acme-plugin")
        _write_yaml_manifest(tmp_path / "other-plugin", "other-plugin")

        reg = PluginRegistry()
        reg.discover(tmp_path)
        reg._plugins["acme-plugin"].tenant_id = "acme"  # noqa: SLF001
        reg._plugins["other-plugin"].tenant_id = "other"  # noqa: SLF001

        visible = reg.list_all(tenant_id="acme")
        names = [m.name for m in visible]
        assert "sys-plugin" in names
        assert "acme-plugin" in names
        assert "other-plugin" not in names

    def test_list_all_tenant_sees_only_system_when_no_own(self, tmp_path: Path) -> None:
        _write_yaml_manifest(tmp_path / "sys-plugin", "sys-plugin")
        _write_yaml_manifest(tmp_path / "other-plugin", "other-plugin")

        reg = PluginRegistry()
        reg.discover(tmp_path)
        reg._plugins["other-plugin"].tenant_id = "other"  # noqa: SLF001

        visible = reg.list_all(tenant_id="acme")
        names = [m.name for m in visible]
        assert names == ["sys-plugin"]


class TestGetTenantFiltering:
    def test_admin_sees_all(self, tmp_path: Path) -> None:
        _write_yaml_manifest(tmp_path / "acme-plugin", "acme-plugin")
        reg = PluginRegistry()
        reg.discover(tmp_path)
        reg._plugins["acme-plugin"].tenant_id = "acme"  # noqa: SLF001
        assert reg.get("acme-plugin") is not None

    def test_owning_tenant_sees_own(self, tmp_path: Path) -> None:
        _write_yaml_manifest(tmp_path / "acme-plugin", "acme-plugin")
        reg = PluginRegistry()
        reg.discover(tmp_path)
        reg._plugins["acme-plugin"].tenant_id = "acme"  # noqa: SLF001
        assert reg.get("acme-plugin", tenant_id="acme") is not None

    def test_other_tenant_cannot_see(self, tmp_path: Path) -> None:
        _write_yaml_manifest(tmp_path / "acme-plugin", "acme-plugin")
        reg = PluginRegistry()
        reg.discover(tmp_path)
        reg._plugins["acme-plugin"].tenant_id = "acme"  # noqa: SLF001
        assert reg.get("acme-plugin", tenant_id="other") is None

    def test_system_plugin_visible_to_all(self, tmp_path: Path) -> None:
        _write_yaml_manifest(tmp_path / "sys-plugin", "sys-plugin")
        reg = PluginRegistry()
        reg.discover(tmp_path)
        # tenant_id="" is default (system)
        assert reg.get("sys-plugin", tenant_id="acme") is not None
        assert reg.get("sys-plugin", tenant_id="other") is not None


# ---------------------------------------------------------------------------
# get_manifest and get_state tenant filtering
# ---------------------------------------------------------------------------


class TestManifestAndStateTenantFiltering:
    def test_get_manifest_respects_tenant(self, tmp_path: Path) -> None:
        _write_yaml_manifest(tmp_path / "acme-plugin", "acme-plugin")
        reg = PluginRegistry()
        reg.discover(tmp_path)
        reg._plugins["acme-plugin"].tenant_id = "acme"  # noqa: SLF001

        assert reg.get_manifest("acme-plugin", tenant_id="acme") is not None
        assert reg.get_manifest("acme-plugin", tenant_id="other") is None

    def test_get_state_respects_tenant(self, tmp_path: Path) -> None:
        _write_yaml_manifest(tmp_path / "acme-plugin", "acme-plugin")
        reg = PluginRegistry()
        reg.discover(tmp_path)
        reg._plugins["acme-plugin"].tenant_id = "acme"  # noqa: SLF001

        assert reg.get_state("acme-plugin", tenant_id="acme") == PluginState.DISCOVERED
        assert reg.get_state("acme-plugin", tenant_id="other") is None


# ---------------------------------------------------------------------------
# list_active tenant filtering
# ---------------------------------------------------------------------------


class TestListActiveTenantFiltering:
    async def test_list_active_filtered(self, tmp_path: Path) -> None:
        for name in ("acme-plugin", "other-plugin"):
            _write_yaml_manifest(tmp_path / name, name)
            _write_plugin_module(tmp_path / name)

        reg = PluginRegistry()
        reg.discover(tmp_path)
        reg._plugins["acme-plugin"].tenant_id = "acme"  # noqa: SLF001
        reg._plugins["other-plugin"].tenant_id = "other"  # noqa: SLF001

        await reg.load_all(_make_context_factory())
        await reg.enable("acme-plugin")
        await reg.enable("other-plugin")

        acme_active = reg.list_active(tenant_id="acme")
        assert len(acme_active) == 1
        assert acme_active[0].name == "acme-plugin"


# ---------------------------------------------------------------------------
# enable / disable tenant isolation
# ---------------------------------------------------------------------------


class TestEnableDisableTenantIsolation:
    async def _setup_loaded_plugin(
        self, tmp_path: Path, name: str, tenant_id: str = ""
    ) -> PluginRegistry:
        _write_yaml_manifest(tmp_path / name, name)
        _write_plugin_module(tmp_path / name)
        reg = PluginRegistry()
        reg.discover(tmp_path)
        await reg.load(name, _make_context_factory(), tenant_id=tenant_id)
        return reg

    async def test_enable_allowed_for_matching_tenant(self, tmp_path: Path) -> None:
        reg = await self._setup_loaded_plugin(tmp_path, "p1", tenant_id="acme")
        await reg.enable("p1", tenant_id="acme")
        assert reg.get_state("p1") == PluginState.ACTIVE

    async def test_enable_allowed_for_admin(self, tmp_path: Path) -> None:
        reg = await self._setup_loaded_plugin(tmp_path, "p1", tenant_id="acme")
        await reg.enable("p1")  # admin mode
        assert reg.get_state("p1") == PluginState.ACTIVE

    async def test_enable_blocked_for_wrong_tenant(self, tmp_path: Path) -> None:
        reg = await self._setup_loaded_plugin(tmp_path, "p1", tenant_id="acme")
        with pytest.raises(PermissionError, match="cannot enable"):
            await reg.enable("p1", tenant_id="other")

    async def test_disable_allowed_for_matching_tenant(self, tmp_path: Path) -> None:
        reg = await self._setup_loaded_plugin(tmp_path, "p1", tenant_id="acme")
        await reg.enable("p1")
        await reg.disable("p1", tenant_id="acme")
        assert reg.get_state("p1") == PluginState.DISABLED

    async def test_disable_blocked_for_wrong_tenant(self, tmp_path: Path) -> None:
        reg = await self._setup_loaded_plugin(tmp_path, "p1", tenant_id="acme")
        await reg.enable("p1")
        with pytest.raises(PermissionError, match="cannot disable"):
            await reg.disable("p1", tenant_id="other")


# ---------------------------------------------------------------------------
# unload / remove tenant isolation
# ---------------------------------------------------------------------------


class TestUnloadRemoveTenantIsolation:
    async def _setup_loaded_plugin(
        self, tmp_path: Path, name: str, tenant_id: str = ""
    ) -> PluginRegistry:
        _write_yaml_manifest(tmp_path / name, name)
        _write_plugin_module(tmp_path / name)
        reg = PluginRegistry()
        reg.discover(tmp_path)
        await reg.load(name, _make_context_factory(), tenant_id=tenant_id)
        return reg

    async def test_unload_allowed_for_matching_tenant(self, tmp_path: Path) -> None:
        reg = await self._setup_loaded_plugin(tmp_path, "p1", tenant_id="acme")
        await reg.unload("p1", tenant_id="acme")
        assert reg.get_state("p1") == PluginState.UNLOADED

    async def test_unload_blocked_for_wrong_tenant(self, tmp_path: Path) -> None:
        reg = await self._setup_loaded_plugin(tmp_path, "p1", tenant_id="acme")
        with pytest.raises(PermissionError, match="cannot unload"):
            await reg.unload("p1", tenant_id="other")

    def test_remove_allowed_for_matching_tenant(self, tmp_path: Path) -> None:
        _write_yaml_manifest(tmp_path / "p1", "p1")
        reg = PluginRegistry()
        reg.discover(tmp_path)
        reg._plugins["p1"].tenant_id = "acme"  # noqa: SLF001

        assert reg.remove("p1", tenant_id="acme") is True
        assert reg.count == 0

    def test_remove_blocked_for_wrong_tenant(self, tmp_path: Path) -> None:
        _write_yaml_manifest(tmp_path / "p1", "p1")
        reg = PluginRegistry()
        reg.discover(tmp_path)
        reg._plugins["p1"].tenant_id = "acme"  # noqa: SLF001

        with pytest.raises(PermissionError, match="cannot remove"):
            reg.remove("p1", tenant_id="other")
        assert reg.count == 1  # still present

    def test_remove_system_plugin_by_admin(self, tmp_path: Path) -> None:
        _write_yaml_manifest(tmp_path / "sys-p", "sys-p")
        reg = PluginRegistry()
        reg.discover(tmp_path)
        assert reg.remove("sys-p") is True
