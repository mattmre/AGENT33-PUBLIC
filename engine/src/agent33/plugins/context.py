"""Plugin execution context with scoped registry access."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class PluginContext:
    """Scoped execution context for a plugin.

    Provides access to system registries and configuration,
    filtered by the plugin's declared permissions. The context
    is immutable after creation.
    """

    # Plugin identity
    plugin_name: str
    plugin_dir: Path
    granted_permissions: frozenset[str] = field(default_factory=frozenset)

    # Registry access (may be permission-gated proxies)
    skill_registry: Any = None  # SkillRegistry or ScopedSkillRegistry
    tool_registry: Any = None  # ToolRegistry or ScopedToolRegistry
    agent_registry: Any = None  # AgentRegistry (read-only for most plugins)
    hook_registry: Any = None  # HookRegistry from H01 (optional)

    # Configuration access
    plugin_config: dict[str, Any] = field(default_factory=dict)
    settings_reader: Any = None  # ReadOnlySettingsProxy

    def has_permission(self, perm: str) -> bool:
        """Check if this context has a specific permission."""
        return perm in self.granted_permissions

    def require_permission(self, perm: str) -> None:
        """Raise PermissionError if the context lacks the permission."""
        if perm not in self.granted_permissions:
            raise PermissionError(
                f"Plugin '{self.plugin_name}' requires permission '{perm}' "
                f"which has not been granted."
            )
