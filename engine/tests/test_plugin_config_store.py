"""Tests for plugin config persistence."""

from __future__ import annotations

from agent33.plugins.config_store import PluginConfigStore
from agent33.services.orchestration_state import OrchestrationStateStore


def test_config_store_persists_records(tmp_path) -> None:
    store_path = tmp_path / "plugin_state.json"
    state_store = OrchestrationStateStore(str(store_path))
    store = PluginConfigStore(state_store)

    record = store.put(
        "alpha-plugin",
        enabled=False,
        config_overrides={"endpoint": "https://example.test"},
        permission_overrides={"network": False},
    )

    assert record.enabled is False
    assert record.config_overrides["endpoint"] == "https://example.test"

    reloaded = PluginConfigStore(OrchestrationStateStore(str(store_path)))
    restored = reloaded.get("alpha-plugin")
    assert restored is not None
    assert restored.enabled is False
    assert restored.permission_overrides["network"] is False


def test_granted_permissions_respect_overrides(tmp_path) -> None:
    store = PluginConfigStore(OrchestrationStateStore(str(tmp_path / "plugin_state.json")))
    store.put(
        "alpha-plugin",
        permission_overrides={"network": False, "config:read": True},
    )

    granted = store.granted_permissions(
        "alpha-plugin",
        manifest_permissions=["network", "config:read", "file:read"],
    )

    assert granted == {"config:read", "file:read"}
