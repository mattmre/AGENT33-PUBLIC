"""Tests for plugin lifecycle API endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from agent33.main import app
from agent33.plugins.config_store import PluginConfigStore
from agent33.plugins.context import PluginContext
from agent33.plugins.doctor import PluginDoctor
from agent33.plugins.events import PluginEventStore
from agent33.plugins.installer import PluginInstaller
from agent33.plugins.manifest import PluginManifest, PluginPermission
from agent33.plugins.models import PluginState
from agent33.plugins.registry import PluginEntry, PluginRegistry
from agent33.security.auth import create_access_token
from agent33.services.orchestration_state import OrchestrationStateStore
from agent33.skills.registry import SkillRegistry


def _client(scopes: list[str], tenant_id: str = "tenant-a") -> TestClient:
    token = create_access_token("test-user", scopes=scopes, tenant_id=tenant_id)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture()
def admin_client() -> TestClient:
    return _client(["admin"], tenant_id="")


@pytest.fixture()
def reader_client() -> TestClient:
    return _client(["plugins:read"])


@pytest.fixture()
def writer_client() -> TestClient:
    return _client(["plugins:read", "plugins:write"])


@pytest.fixture()
def no_scope_client() -> TestClient:
    return _client([], tenant_id="tenant-a")


@pytest.fixture()
def anonymous_client() -> TestClient:
    return TestClient(app)


def _make_manifest(name: str = "test-plugin", **kwargs: Any) -> PluginManifest:
    defaults: dict[str, Any] = {
        "version": "1.0.0",
        "description": "Test plugin",
        "author": "test-team",
    }
    defaults.update(kwargs)
    return PluginManifest(name=name, **defaults)


def _make_entry(
    name: str = "test-plugin",
    state: PluginState = PluginState.ACTIVE,
    **kwargs: Any,
) -> PluginEntry:
    manifest = _make_manifest(name, **kwargs)
    entry = PluginEntry(manifest, Path("/tmp") / name)
    entry.state = state
    return entry


def _setup_registry_with_plugins(
    plugins: list[dict[str, Any]] | None = None,
) -> PluginRegistry:
    """Create a PluginRegistry with pre-populated entries for testing."""
    registry = PluginRegistry()
    if plugins is None:
        plugins = [
            {
                "name": "alpha-plugin",
                "state": PluginState.ACTIVE,
                "description": "Alpha plugin",
                "tags": ["infra"],
            },
            {
                "name": "beta-plugin",
                "state": PluginState.LOADED,
                "description": "Beta plugin",
                "tags": ["testing"],
            },
        ]
    for p in plugins:
        name = p.pop("name")
        state = p.pop("state", PluginState.DISCOVERED)
        tenant_id = p.pop("tenant_id", "")
        manifest = _make_manifest(name, **{k: v for k, v in p.items() if k != "state"})
        entry = PluginEntry(manifest, Path("/tmp") / name)
        entry.state = state
        entry.tenant_id = tenant_id
        registry._plugins[name] = entry
    return registry


@pytest.fixture(autouse=True)
def setup_plugin_registry(tmp_path) -> None:
    """Set up a mock plugin registry on app.state for each test."""
    registry = _setup_registry_with_plugins()
    state_store = OrchestrationStateStore(str(tmp_path / "plugin_state.json"))
    event_store = PluginEventStore(state_store)
    config_store = PluginConfigStore(state_store)

    def context_factory(manifest, plugin_dir: Path) -> PluginContext:  # type: ignore[no-untyped-def]
        return PluginContext(
            plugin_name=manifest.name,
            plugin_dir=plugin_dir,
            granted_permissions=frozenset(permission.value for permission in manifest.permissions),
            skill_registry=SkillRegistry(),
            tool_registry=MagicMock(),
            agent_registry=MagicMock(),
            plugin_config={},
        )

    installer = PluginInstaller(
        registry,
        plugins_dir=tmp_path / "managed-plugins",
        context_factory=context_factory,
        event_store=event_store,
        state_store=state_store,
    )
    app.state.plugin_registry = registry
    app.state.plugin_context_factory = context_factory
    app.state.plugin_event_store = event_store
    app.state.plugin_config_store = config_store
    app.state.plugin_installer = installer
    app.state.plugin_doctor = PluginDoctor(
        registry,
        config_store=config_store,
        installer=installer,
    )
    yield
    for attr in (
        "plugin_registry",
        "plugin_context_factory",
        "plugin_event_store",
        "plugin_config_store",
        "plugin_installer",
        "plugin_doctor",
    ):
        if hasattr(app.state, attr):
            delattr(app.state, attr)


class TestListPlugins:
    """Tests for GET /v1/plugins."""

    def test_list_plugins_returns_all(self, reader_client: TestClient) -> None:
        response = reader_client.get("/v1/plugins")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        names = [p["name"] for p in data]
        assert "alpha-plugin" in names
        assert "beta-plugin" in names

    def test_list_plugins_has_summary_shape(self, reader_client: TestClient) -> None:
        response = reader_client.get("/v1/plugins")
        data = response.json()
        plugin = data[0]
        assert "name" in plugin
        assert "version" in plugin
        assert "state" in plugin
        assert "contributions_summary" in plugin

    def test_list_plugins_requires_auth(self, anonymous_client: TestClient) -> None:
        response = anonymous_client.get("/v1/plugins")
        assert response.status_code == 401

    def test_list_plugins_requires_scope(self, no_scope_client: TestClient) -> None:
        response = no_scope_client.get("/v1/plugins")
        assert response.status_code == 403


class TestGetPlugin:
    """Tests for GET /v1/plugins/{name}."""

    def test_get_existing_plugin(self, reader_client: TestClient) -> None:
        response = reader_client.get("/v1/plugins/alpha-plugin")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "alpha-plugin"
        assert data["state"] == "active"
        assert "version" in data
        assert "contributions" in data
        assert "permissions" in data

    def test_get_nonexistent_plugin_returns_404(self, reader_client: TestClient) -> None:
        response = reader_client.get("/v1/plugins/nonexistent")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_get_plugin_without_instance_does_not_duplicate_permissions(
        self, reader_client: TestClient
    ) -> None:
        registry = app.state.plugin_registry
        entry = registry.get("alpha-plugin")
        entry.manifest.permissions = [PluginPermission.CONFIG_READ]  # type: ignore[misc]

        response = reader_client.get("/v1/plugins/alpha-plugin")

        assert response.status_code == 200
        assert response.json()["permissions"] == ["config:read"]
        assert response.json()["granted_permissions"] == []
        assert response.json()["denied_permissions"] == []


class TestEnablePlugin:
    """Tests for POST /v1/plugins/{name}/enable."""

    def test_enable_loaded_plugin(self, writer_client: TestClient) -> None:
        response = writer_client.post("/v1/plugins/beta-plugin/enable")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "beta-plugin"
        assert data["state"] == "active"

    def test_enable_already_active_returns_conflict(self, writer_client: TestClient) -> None:
        response = writer_client.post("/v1/plugins/alpha-plugin/enable")
        # alpha-plugin is already ACTIVE, so this should fail
        assert response.status_code == 409

    def test_enable_nonexistent_returns_404(self, writer_client: TestClient) -> None:
        response = writer_client.post("/v1/plugins/ghost/enable")
        assert response.status_code == 404

    def test_enable_requires_write_scope(self, reader_client: TestClient) -> None:
        response = reader_client.post("/v1/plugins/beta-plugin/enable")
        assert response.status_code == 403


class TestDisablePlugin:
    """Tests for POST /v1/plugins/{name}/disable."""

    def test_disable_active_plugin(self, writer_client: TestClient) -> None:
        response = writer_client.post("/v1/plugins/alpha-plugin/disable")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "alpha-plugin"
        assert data["state"] == "disabled"

    def test_disable_non_active_returns_conflict(self, writer_client: TestClient) -> None:
        response = writer_client.post("/v1/plugins/beta-plugin/disable")
        # beta-plugin is LOADED, not ACTIVE
        assert response.status_code == 409

    def test_disable_nonexistent_returns_404(self, writer_client: TestClient) -> None:
        response = writer_client.post("/v1/plugins/ghost/disable")
        assert response.status_code == 404

    def test_disable_requires_write_scope(self, reader_client: TestClient) -> None:
        response = reader_client.post("/v1/plugins/alpha-plugin/disable")
        assert response.status_code == 403


class TestSearchPlugins:
    """Tests for GET /v1/plugins/search."""

    def test_search_by_name(self, reader_client: TestClient) -> None:
        response = reader_client.get("/v1/plugins/search?q=alpha")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["plugins"][0]["name"] == "alpha-plugin"

    def test_search_by_description(self, reader_client: TestClient) -> None:
        response = reader_client.get("/v1/plugins/search?q=Beta")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1

    def test_search_no_results(self, reader_client: TestClient) -> None:
        response = reader_client.get("/v1/plugins/search?q=nonexistent")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 0
        assert data["plugins"] == []

    def test_search_empty_query_returns_all(self, reader_client: TestClient) -> None:
        response = reader_client.get("/v1/plugins/search?q=")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2


class TestPluginHealth:
    """Tests for GET /v1/plugins/{name}/health."""

    def test_active_plugin_is_healthy(self, reader_client: TestClient) -> None:
        response = reader_client.get("/v1/plugins/alpha-plugin/health")
        assert response.status_code == 200
        data = response.json()
        assert data["plugin_name"] == "alpha-plugin"
        assert data["healthy"] is True
        assert data["details"]["state"] == "active"

    def test_loaded_plugin_is_not_healthy(self, reader_client: TestClient) -> None:
        response = reader_client.get("/v1/plugins/beta-plugin/health")
        assert response.status_code == 200
        data = response.json()
        assert data["healthy"] is False
        assert data["details"]["state"] == "loaded"

    def test_health_nonexistent_returns_404(self, reader_client: TestClient) -> None:
        response = reader_client.get("/v1/plugins/ghost/health")
        assert response.status_code == 404

    def test_error_state_shows_error(self, reader_client: TestClient) -> None:
        """Plugin in ERROR state includes error details."""
        registry = app.state.plugin_registry
        entry = registry.get("alpha-plugin")
        entry.state = PluginState.ERROR
        entry.error = "Something went wrong"

        response = reader_client.get("/v1/plugins/alpha-plugin/health")
        data = response.json()
        assert data["healthy"] is False
        assert "Something went wrong" in data["details"]["error"]


class TestPluginConfig:
    """Tests for GET/PUT /v1/plugins/{name}/config."""

    def test_get_config_returns_empty_for_no_instance(self, reader_client: TestClient) -> None:
        response = reader_client.get("/v1/plugins/alpha-plugin/config")
        assert response.status_code == 200
        assert response.json() == {}

    def test_update_config(self, writer_client: TestClient) -> None:
        response = writer_client.put(
            "/v1/plugins/alpha-plugin/config",
            json={
                "config": {"key": "value"},
                "enabled": True,
                "permission_overrides": {"network": False},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["plugin_name"] == "alpha-plugin"
        assert data["updated"] is True
        assert data["config"]["key"] == "value"
        assert data["permission_overrides"]["network"] is False

    def test_get_config_returns_persisted_record(self, writer_client: TestClient) -> None:
        writer_client.put(
            "/v1/plugins/alpha-plugin/config",
            json={"config": {"key": "value"}, "enabled": False},
        )

        response = writer_client.get("/v1/plugins/alpha-plugin/config")

        assert response.status_code == 200
        assert response.json()["config_overrides"]["key"] == "value"
        assert response.json()["enabled"] is False

    def test_update_config_nonexistent_returns_404(self, writer_client: TestClient) -> None:
        response = writer_client.put(
            "/v1/plugins/ghost/config",
            json={"config": {}},
        )
        assert response.status_code == 404


class TestDiscoverPlugins:
    """Tests for POST /v1/plugins/discover."""

    def test_discover_requires_admin(self, writer_client: TestClient) -> None:
        response = writer_client.post("/v1/plugins/discover")
        assert response.status_code == 403

    def test_discover_with_admin_scope(self, admin_client: TestClient) -> None:
        response = admin_client.post("/v1/plugins/discover")
        assert response.status_code == 200
        data = response.json()
        assert "discovered" in data
        assert "total" in data


class TestReloadPlugin:
    """Tests for POST /v1/plugins/{name}/reload."""

    def test_reload_requires_admin(self, writer_client: TestClient) -> None:
        response = writer_client.post("/v1/plugins/alpha-plugin/reload")
        assert response.status_code == 403

    def test_reload_nonexistent_returns_404(self, admin_client: TestClient) -> None:
        response = admin_client.post("/v1/plugins/ghost/reload")
        assert response.status_code == 404

    def test_reload_without_context_factory_returns_503(self, admin_client: TestClient) -> None:
        """Reload requires plugin_context_factory on app state."""
        # Ensure no context factory
        if hasattr(app.state, "plugin_context_factory"):
            delattr(app.state, "plugin_context_factory")
        response = admin_client.post("/v1/plugins/alpha-plugin/reload")
        assert response.status_code == 503


def _write_local_plugin(base_dir: Path, name: str, *, version: str = "1.0.0") -> Path:
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
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return plugin_dir


class TestPluginLifecycleRoutes:
    def test_install_requires_admin(self, writer_client: TestClient, tmp_path) -> None:
        source = _write_local_plugin(tmp_path / "sources", "local-plugin")

        response = writer_client.post(
            "/v1/plugins/install",
            json={"source_path": str(source), "mode": "copy"},
        )

        assert response.status_code == 403

    def test_install_plugin_from_local_path(self, admin_client: TestClient, tmp_path) -> None:
        source = _write_local_plugin(tmp_path / "sources", "local-plugin")

        response = admin_client.post(
            "/v1/plugins/install",
            json={"source_path": str(source), "mode": "copy"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["plugin_name"] == "local-plugin"

    def test_plugin_permissions_endpoint(self, reader_client: TestClient) -> None:
        registry = app.state.plugin_registry
        entry = registry.get("alpha-plugin")
        entry.manifest.permissions = []  # type: ignore[misc]

        response = reader_client.get("/v1/plugins/alpha-plugin/permissions")

        assert response.status_code == 200
        assert response.json()["plugin_name"] == "alpha-plugin"

    def test_plugin_permissions_without_instance_returns_empty_granted_and_denied(
        self, reader_client: TestClient
    ) -> None:
        registry = app.state.plugin_registry
        entry = registry.get("alpha-plugin")
        entry.manifest.permissions = [PluginPermission.CONFIG_READ]  # type: ignore[misc]

        response = reader_client.get("/v1/plugins/alpha-plugin/permissions")

        assert response.status_code == 200
        assert response.json()["requested"] == ["config:read"]
        assert response.json()["granted"] == []
        assert response.json()["denied"] == []

    def test_plugin_doctor_endpoint(self, reader_client: TestClient) -> None:
        response = reader_client.get("/v1/plugins/alpha-plugin/doctor")

        assert response.status_code == 200
        assert response.json()["plugin_name"] == "alpha-plugin"
        assert "overall_status" in response.json()

    def test_plugin_doctor_endpoint_respects_tenant_visibility(
        self, reader_client: TestClient
    ) -> None:
        registry = app.state.plugin_registry
        registry.get("alpha-plugin").tenant_id = "tenant-b"  # type: ignore[union-attr]

        response = reader_client.get("/v1/plugins/alpha-plugin/doctor")

        assert response.status_code == 404

    def test_plugin_doctor_summary_filters_to_visible_tenants(
        self, reader_client: TestClient
    ) -> None:
        registry = app.state.plugin_registry
        registry.get("alpha-plugin").tenant_id = ""  # type: ignore[union-attr]
        registry.get("beta-plugin").tenant_id = "tenant-b"  # type: ignore[union-attr]

        response = reader_client.get("/v1/plugins/doctor")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert [report["plugin_name"] for report in data["reports"]] == ["alpha-plugin"]

    def test_plugin_events_endpoint_returns_config_update_event(
        self, writer_client: TestClient
    ) -> None:
        writer_client.put(
            "/v1/plugins/alpha-plugin/config",
            json={"config": {"mode": "safe"}},
        )

        response = writer_client.get("/v1/plugins/alpha-plugin/events")

        assert response.status_code == 200
        assert response.json()["count"] >= 1
        assert any(event["event_type"] == "config_updated" for event in response.json()["events"])
