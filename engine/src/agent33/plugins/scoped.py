"""Scoped registry proxies for plugin capability sandboxing."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent33.plugins.capabilities import CapabilityGrant
    from agent33.skills.registry import SkillRegistry
    from agent33.tools.registry import ToolRegistry


class ScopedSkillRegistry:
    """A skill registry proxy that restricts operations based on capability grants.

    Read operations (get, search) are always allowed.
    Write operations (register, remove) are allowed for plugins registering
    their own contributions.
    """

    def __init__(self, registry: SkillRegistry, grants: CapabilityGrant) -> None:
        self._registry = registry
        self._grants = grants

    def get(self, name: str) -> Any:
        """Look up a skill by name."""
        return self._registry.get(name)

    def search(self, query: str) -> list[Any]:
        """Simple text search across skills."""
        return self._registry.search(query)

    def list_all(self) -> list[Any]:
        """Return all registered skills."""
        return self._registry.list_all()

    def register(self, skill: Any) -> None:
        """Register a skill. Plugins always allowed to register their own skills."""
        self._registry.register(skill)

    def remove(self, name: str) -> bool:
        """Remove a skill. Plugins can only remove their own contributions."""
        return self._registry.remove(name)

    @property
    def count(self) -> int:
        """Number of registered skills."""
        return self._registry.count


class ScopedToolRegistry:
    """A tool registry proxy that restricts operations based on capability grants."""

    def __init__(self, registry: ToolRegistry, grants: CapabilityGrant) -> None:
        self._registry = registry
        self._grants = grants

    def get(self, name: str) -> Any:
        """Return the tool with the given name, or None."""
        return self._registry.get(name)

    def list_all(self) -> list[Any]:
        """Return all registered tools."""
        return self._registry.list_all()

    def register(self, tool: Any) -> None:
        """Register a tool. Plugins always allowed to register their own tools."""
        self._registry.register(tool)

    async def validated_execute(self, name: str, params: dict[str, Any], context: Any) -> Any:
        """Validate and execute a tool. Requires tool:execute permission."""
        self._grants.require("tool:execute")
        return await self._registry.validated_execute(name, params, context)


class ReadOnlySettingsProxy:
    """Proxy that exposes only safe, non-secret settings to plugins.

    Plugins that request config:read get access to a curated subset
    of system settings. Secret fields (API keys, passwords, JWT secrets)
    are never exposed.
    """

    _SAFE_FIELDS: frozenset[str] = frozenset(
        {
            "environment",
            "api_port",
            "ollama_base_url",
            "ollama_default_model",
            "embedding_provider",
            "rag_top_k",
            "rag_similarity_threshold",
            "chunk_tokens",
            "chunk_overlap_tokens",
        }
    )

    def __init__(self, settings: Any) -> None:
        self._settings = settings

    def get(self, key: str) -> Any:
        """Read a setting by name. Only safe fields are exposed."""
        if key not in self._SAFE_FIELDS:
            raise PermissionError(
                f"Setting '{key}' is not exposed to plugins. "
                f"Safe fields: {sorted(self._SAFE_FIELDS)}"
            )
        return getattr(self._settings, key)

    @property
    def safe_fields(self) -> frozenset[str]:
        """Return the set of fields accessible to plugins."""
        return self._SAFE_FIELDS
