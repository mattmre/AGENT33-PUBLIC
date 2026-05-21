"""Multi-tenant plugin configuration and visibility rules."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agent33.plugins.manifest import PluginManifest
    from agent33.plugins.registry import PluginRegistry


class TenantPluginConfig(BaseModel):
    """Per-tenant configuration for a plugin.

    Stored in the database with tenant_id as part of the key.
    """

    tenant_id: str
    plugin_name: str
    enabled: bool = True
    config_overrides: dict[str, Any] = Field(default_factory=dict)
    permission_overrides: dict[str, bool] = Field(
        default_factory=dict,
        description=(
            "Per-tenant permission overrides. "
            "Keys are PluginPermission values, values are True (grant) or False (deny). "
            "Unspecified permissions use the admin default."
        ),
    )


class TenantPluginState(BaseModel):
    """Runtime state for a plugin in a specific tenant context."""

    tenant_id: str
    plugin_name: str
    is_enabled: bool = True
    custom_config: dict[str, Any] = Field(default_factory=dict)


def get_visible_plugins(
    tenant_id: str,
    plugin_registry: PluginRegistry,
    tenant_configs: dict[str, TenantPluginConfig],
) -> list[PluginManifest]:
    """Return plugins visible to a specific tenant.

    Visibility rules:
    1. SYSTEM plugins are always visible
    2. SHARED plugins are visible if the tenant hasn't disabled them
    3. TENANT plugins are visible only to their owning tenant
    """
    visible: list[PluginManifest] = []
    for manifest in plugin_registry.list_all():
        entry = plugin_registry.get(manifest.name)
        if entry is None:
            continue

        scope = getattr(entry.manifest, "scope", "system")

        if scope == "system":
            visible.append(manifest)
        elif scope == "shared":
            config_key = f"{tenant_id}:{manifest.name}"
            config = tenant_configs.get(config_key)
            if config is None or config.enabled:
                visible.append(manifest)
        elif scope == "tenant":
            config_key = f"{tenant_id}:{manifest.name}"
            config = tenant_configs.get(config_key)
            if config is not None and config.enabled:
                visible.append(manifest)

    return visible
