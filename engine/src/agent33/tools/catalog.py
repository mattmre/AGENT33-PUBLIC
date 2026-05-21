"""Tool catalog service: aggregates tools from all sources with metadata.

Provides a unified view of all available tools across ToolRegistry,
SkillRegistry, and plugin contributions with search, filtering,
and JSON Schema lookup.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from agent33.tools.schema import get_tool_schema

if TYPE_CHECKING:
    from agent33.plugins.registry import PluginRegistry
    from agent33.skills.registry import SkillRegistry
    from agent33.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class ToolProvider(StrEnum):
    """Source of a tool registration."""

    BUILTIN = "builtin"
    ENTRYPOINT = "entrypoint"
    SKILL = "skill"
    PLUGIN = "plugin"
    MCP = "mcp"
    YAML = "yaml"


class CatalogEntry(BaseModel):
    """Unified tool metadata for the catalog."""

    name: str
    description: str = ""
    provider: ToolProvider = ToolProvider.BUILTIN
    provider_name: str = ""
    category: str = "general"
    version: str = ""
    enabled: bool = True
    has_schema: bool = False
    parameters_schema: dict[str, Any] = Field(default_factory=dict)
    result_schema: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class CatalogSearchRequest(BaseModel):
    """Request body for catalog search."""

    query: str = ""
    categories: list[str] = Field(default_factory=list)
    providers: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class CatalogPage(BaseModel):
    """Paginated catalog response."""

    tools: list[CatalogEntry]
    total: int
    limit: int
    offset: int


class CategoryCount(BaseModel):
    """Category with tool count."""

    category: str
    count: int


class ProviderCount(BaseModel):
    """Provider with tool count."""

    provider: str
    count: int


class ToolCatalogService:
    """Aggregates tools from ToolRegistry, SkillRegistry, and plugins.

    Provides a single unified catalog with search, filtering,
    schema lookup, and category/provider summaries.
    """

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        skill_registry: SkillRegistry | None = None,
        plugin_registry: PluginRegistry | None = None,
    ) -> None:
        self._tool_registry = tool_registry
        self._skill_registry = skill_registry
        self._plugin_registry = plugin_registry

    def _aggregate_entries(self, *, tenant_id: str = "") -> list[CatalogEntry]:
        """Collect catalog entries from all sources."""
        entries: list[CatalogEntry] = []

        # -- Tools from ToolRegistry ----------------------------------------
        if self._tool_registry is not None:
            for tool in self._tool_registry.list_all():
                entry_meta = self._tool_registry.get_entry(tool.name)
                schema: dict[str, Any] = {}
                result_schema: dict[str, Any] = {}
                tags: list[str] = []
                version = ""
                category = "general"

                if entry_meta is not None:
                    result_schema = entry_meta.result_schema
                    tags = list(entry_meta.tags)
                    version = entry_meta.version
                    if tags:
                        category = tags[0]

                schema = get_tool_schema(tool, entry_meta) or {}

                entries.append(
                    CatalogEntry(
                        name=tool.name,
                        description=tool.description,
                        provider=ToolProvider.BUILTIN,
                        provider_name="tool-registry",
                        category=category,
                        version=version,
                        enabled=True,
                        has_schema=bool(schema),
                        parameters_schema=schema,
                        result_schema=result_schema,
                        tags=tags,
                    )
                )

            # YAML-only entries (no runtime Tool instance)
            for entry_meta in self._tool_registry.list_entries():
                if self._tool_registry.get(entry_meta.name) is None:
                    tags = list(entry_meta.tags)
                    category = tags[0] if tags else "general"
                    entries.append(
                        CatalogEntry(
                            name=entry_meta.name,
                            description=entry_meta.description,
                            provider=ToolProvider.YAML,
                            provider_name="yaml-definitions",
                            category=category,
                            version=entry_meta.version,
                            enabled=entry_meta.status.value == "active",
                            has_schema=bool(entry_meta.parameters_schema),
                            parameters_schema=entry_meta.parameters_schema,
                            result_schema=entry_meta.result_schema,
                            tags=tags,
                        )
                    )

        # -- Skill catalog entries -----------------------------------------
        if self._skill_registry is not None:
            for skill in self._skill_registry.list_all():
                entries.append(
                    CatalogEntry(
                        name=f"skill:{skill.name}",
                        description=skill.description,
                        provider=ToolProvider.SKILL,
                        provider_name=skill.name,
                        category="skill",
                        version=skill.version,
                        enabled=skill.status.value == "active",
                        has_schema=False,
                        tags=list(skill.tags),
                    )
                )

        # -- Plugin contributions -------------------------------------------
        if self._plugin_registry is not None:
            for manifest in self._plugin_registry.list_all(tenant_id=tenant_id):
                state = self._plugin_registry.get_state(manifest.name, tenant_id=tenant_id)
                is_active = state is not None and state.value == "active"
                for tool_name in manifest.contributions.tools:
                    entries.append(
                        CatalogEntry(
                            name=f"plugin:{manifest.name}:{tool_name}",
                            description=f"Tool '{tool_name}' from plugin {manifest.name}",
                            provider=ToolProvider.PLUGIN,
                            provider_name=manifest.name,
                            category="plugin",
                            version=manifest.version,
                            enabled=is_active,
                            has_schema=False,
                            tags=list(manifest.tags),
                        )
                    )

        return entries

    def list_tools(
        self,
        *,
        category: str | None = None,
        provider: str | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
        tenant_id: str = "",
    ) -> CatalogPage:
        """List tools with optional filtering and pagination."""
        entries = self._aggregate_entries(tenant_id=tenant_id)

        if category:
            entries = [e for e in entries if e.category == category]

        if provider:
            entries = [e for e in entries if e.provider.value == provider]

        if search:
            q = search.lower()
            entries = [
                e
                for e in entries
                if q in e.name.lower()
                or q in e.description.lower()
                or any(q in t.lower() for t in e.tags)
            ]

        total = len(entries)
        entries.sort(key=lambda e: e.name)
        page = entries[offset : offset + limit]

        return CatalogPage(tools=page, total=total, limit=limit, offset=offset)

    def get_tool(self, name: str, *, tenant_id: str = "") -> CatalogEntry | None:
        """Get a single tool by name."""
        for entry in self._aggregate_entries(tenant_id=tenant_id):
            if entry.name == name:
                return entry
        return None

    def get_schema(self, name: str, *, tenant_id: str = "") -> dict[str, Any] | None:
        """Get the JSON Schema for a tool by name.

        Returns the parameters_schema if available, or None.
        """
        entry = self.get_tool(name, tenant_id=tenant_id)
        if entry is None:
            return None
        if entry.parameters_schema:
            return entry.parameters_schema
        return None

    def list_categories(self, *, tenant_id: str = "") -> list[CategoryCount]:
        """List all categories with tool counts."""
        counts: dict[str, int] = {}
        for entry in self._aggregate_entries(tenant_id=tenant_id):
            counts[entry.category] = counts.get(entry.category, 0) + 1
        return sorted(
            [CategoryCount(category=k, count=v) for k, v in counts.items()],
            key=lambda c: (-c.count, c.category),
        )

    def list_providers(self, *, tenant_id: str = "") -> list[ProviderCount]:
        """List all providers with tool counts."""
        counts: dict[str, int] = {}
        for entry in self._aggregate_entries(tenant_id=tenant_id):
            prov = entry.provider.value
            counts[prov] = counts.get(prov, 0) + 1
        return sorted(
            [ProviderCount(provider=k, count=v) for k, v in counts.items()],
            key=lambda c: (-c.count, c.provider),
        )

    def search(self, request: CatalogSearchRequest, *, tenant_id: str = "") -> CatalogPage:
        """Full search with multiple filter criteria."""
        entries = self._aggregate_entries(tenant_id=tenant_id)

        if request.query:
            q = request.query.lower()
            entries = [
                e
                for e in entries
                if q in e.name.lower()
                or q in e.description.lower()
                or any(q in t.lower() for t in e.tags)
            ]

        if request.categories:
            entries = [e for e in entries if e.category in request.categories]

        if request.providers:
            entries = [e for e in entries if e.provider.value in request.providers]

        if request.tags:
            request_tags_lower = {t.lower() for t in request.tags}
            entries = [e for e in entries if any(t.lower() in request_tags_lower for t in e.tags)]

        total = len(entries)
        entries.sort(key=lambda e: e.name)
        page = entries[request.offset : request.offset + request.limit]

        return CatalogPage(tools=page, total=total, limit=request.limit, offset=request.offset)
