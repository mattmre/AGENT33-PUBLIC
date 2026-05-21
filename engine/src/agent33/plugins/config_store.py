"""Plugin configuration persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent33.plugins.tenant import TenantPluginConfig

if TYPE_CHECKING:
    from agent33.services.orchestration_state import OrchestrationStateStore


class PluginConfigStore:
    """Persist plugin config and permission overrides."""

    def __init__(
        self,
        state_store: OrchestrationStateStore | None = None,
        *,
        namespace: str = "plugin_configs",
    ) -> None:
        self._state_store = state_store
        self._namespace = namespace
        self._configs: dict[str, TenantPluginConfig] = {}
        self._load()

    def get(self, plugin_name: str, *, tenant_id: str = "") -> TenantPluginConfig | None:
        """Return stored config for one plugin/tenant pair."""
        return self._configs.get(self._key(plugin_name, tenant_id))

    def put(
        self,
        plugin_name: str,
        *,
        tenant_id: str = "",
        enabled: bool | None = None,
        config_overrides: dict[str, Any] | None = None,
        permission_overrides: dict[str, bool] | None = None,
    ) -> TenantPluginConfig:
        """Create or update one plugin config record."""
        existing = self.get(plugin_name, tenant_id=tenant_id)
        record = TenantPluginConfig(
            tenant_id=tenant_id,
            plugin_name=plugin_name,
            enabled=existing.enabled if existing is not None else True,
            config_overrides=dict(existing.config_overrides) if existing is not None else {},
            permission_overrides=(
                dict(existing.permission_overrides) if existing is not None else {}
            ),
        )
        if enabled is not None:
            record.enabled = enabled
        if config_overrides:
            record.config_overrides.update(config_overrides)
        if permission_overrides:
            record.permission_overrides.update(permission_overrides)
        self._configs[self._key(plugin_name, tenant_id)] = record
        self._persist()
        return record

    def delete(self, plugin_name: str, *, tenant_id: str = "") -> None:
        """Remove persisted config for one plugin/tenant pair."""
        self._configs.pop(self._key(plugin_name, tenant_id), None)
        self._persist()

    def granted_permissions(
        self,
        plugin_name: str,
        *,
        tenant_id: str = "",
        manifest_permissions: list[str],
    ) -> set[str]:
        """Return the manifest permissions allowed by stored overrides."""
        record = self.get(plugin_name, tenant_id=tenant_id)
        if record is None:
            return set(manifest_permissions)
        granted: set[str] = set()
        for permission in manifest_permissions:
            if record.permission_overrides.get(permission, True):
                granted.add(permission)
        return granted

    def _key(self, plugin_name: str, tenant_id: str) -> str:
        normalized_tenant = tenant_id or "__global__"
        return f"{normalized_tenant}:{plugin_name}"

    def _load(self) -> None:
        if self._state_store is None:
            return
        payload = self._state_store.read_namespace(self._namespace)
        raw_configs = payload.get("configs", {})
        if not isinstance(raw_configs, dict):
            return
        self._configs = {}
        for key, value in raw_configs.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                continue
            try:
                self._configs[key] = TenantPluginConfig.model_validate(value)
            except Exception:
                continue

    def _persist(self) -> None:
        if self._state_store is None:
            return
        self._state_store.write_namespace(
            self._namespace,
            {
                "configs": {
                    key: value.model_dump(mode="json") for key, value in self._configs.items()
                },
            },
        )
