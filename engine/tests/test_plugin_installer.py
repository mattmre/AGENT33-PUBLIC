"""Tests for plugin install, link, and update flows."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from agent33.plugins.context import PluginContext
from agent33.plugins.events import PluginEventStore
from agent33.plugins.installer import PluginInstaller, PluginInstallMode
from agent33.plugins.models import PluginState
from agent33.plugins.registry import PluginRegistry
from agent33.services.orchestration_state import OrchestrationStateStore
from agent33.skills.registry import SkillRegistry


def _write_plugin(base_dir: Path, name: str, *, version: str = "1.0.0") -> Path:
    plugin_dir = base_dir / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.yaml").write_text(
        "\n".join(
            [
                f"name: {name}",
                f"version: {version}",
                f"description: Test plugin {name}",
                'entry_point: "plugin:Plugin"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (plugin_dir / "plugin.py").write_text(
        "\n".join(
            [
                "from agent33.plugins.base import PluginBase",
                "",
                "class Plugin(PluginBase):",
                "    async def on_load(self):",
                "        return None",
                "",
                "    async def on_enable(self):",
                "        return None",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return plugin_dir


def _context_factory(manifest, plugin_dir: Path) -> PluginContext:  # type: ignore[no-untyped-def]
    return PluginContext(
        plugin_name=manifest.name,
        plugin_dir=plugin_dir,
        granted_permissions=frozenset(),
        skill_registry=SkillRegistry(),
        tool_registry=MagicMock(),
        agent_registry=MagicMock(),
    )


class TestPluginInstaller:
    async def test_install_from_local_copy_records_metadata_and_events(self, tmp_path) -> None:
        source = _write_plugin(tmp_path / "sources", "alpha-plugin")
        state_store = OrchestrationStateStore(str(tmp_path / "plugin_state.json"))
        event_store = PluginEventStore(state_store)
        registry = PluginRegistry(event_store=event_store)
        installer = PluginInstaller(
            registry,
            plugins_dir=tmp_path / "managed",
            context_factory=_context_factory,
            event_store=event_store,
            state_store=state_store,
        )

        result = await installer.install_from_local(source, requested_by="tester")

        assert result.success is True
        assert result.plugin_name == "alpha-plugin"
        assert result.mode == PluginInstallMode.COPY
        assert Path(result.installed_path).is_dir()
        assert registry.get_state("alpha-plugin") == PluginState.ACTIVE
        events = event_store.list(plugin_name="alpha-plugin")
        assert {event.event_type for event in events} >= {
            "installed",
            "discovered",
            "loaded",
            "enabled",
        }

    async def test_install_from_local_link_keeps_source_path(self, tmp_path) -> None:
        source = _write_plugin(tmp_path / "sources", "beta-plugin")
        state_store = OrchestrationStateStore(str(tmp_path / "plugin_state.json"))
        registry = PluginRegistry()
        installer = PluginInstaller(
            registry,
            plugins_dir=tmp_path / "managed",
            context_factory=_context_factory,
            state_store=state_store,
        )

        result = await installer.install_from_local(source, mode=PluginInstallMode.LINK)

        assert result.success is True
        assert result.linked is True
        assert result.installed_path == str(source.resolve())
        assert installer.get_record("beta-plugin").linked is True

    async def test_update_refreshes_copied_plugin_version(self, tmp_path) -> None:
        source = _write_plugin(tmp_path / "sources", "gamma-plugin", version="1.0.0")
        state_store = OrchestrationStateStore(str(tmp_path / "plugin_state.json"))
        event_store = PluginEventStore(state_store)
        registry = PluginRegistry(event_store=event_store)
        installer = PluginInstaller(
            registry,
            plugins_dir=tmp_path / "managed",
            context_factory=_context_factory,
            event_store=event_store,
            state_store=state_store,
        )

        initial = await installer.install_from_local(source)
        assert initial.success is True

        (source / "plugin.yaml").write_text(
            "\n".join(
                [
                    "name: gamma-plugin",
                    "version: 1.1.0",
                    "description: Test plugin gamma-plugin",
                    'entry_point: "plugin:Plugin"',
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        updated = await installer.update("gamma-plugin", requested_by="tester")

        assert updated.success is True
        assert updated.version == "1.1.0"
        assert registry.get("gamma-plugin").manifest.version == "1.1.0"
        assert any(
            event.event_type == "updated" for event in event_store.list(plugin_name="gamma-plugin")
        )
