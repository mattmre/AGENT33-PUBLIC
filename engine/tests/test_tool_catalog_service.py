"""Tests for ToolCatalogService: aggregation, search, filtering, schema lookup."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from agent33.tools.catalog import (
    CatalogSearchRequest,
    ToolCatalogService,
    ToolProvider,
)
from agent33.tools.registry_entry import ToolRegistryEntry, ToolStatus

# ---------------------------------------------------------------------------
# Helpers: build mock registries
# ---------------------------------------------------------------------------


class _ToolStub:
    def __init__(self, name: str, description: str = "A tool") -> None:
        self.name = name
        self.description = description


class _SchemaToolStub(_ToolStub):
    def __init__(
        self,
        name: str,
        description: str = "Schema tool",
        schema: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.parameters_schema = schema or {"type": "object", "properties": {}}

    async def execute(self, params: dict[str, Any], context: Any) -> None:  # noqa: ARG002
        return None


def _make_tool(name: str, description: str = "A tool") -> Any:
    """Create a lightweight Tool object."""
    return _ToolStub(name=name, description=description)


def _make_schema_tool(
    name: str, description: str = "Schema tool", schema: dict[str, Any] | None = None
) -> Any:
    """Create a lightweight SchemaAwareTool."""
    return _SchemaToolStub(name=name, description=description, schema=schema)


def _make_entry(
    name: str,
    version: str = "1.0.0",
    description: str = "",
    tags: list[str] | None = None,
    status: ToolStatus = ToolStatus.ACTIVE,
    parameters_schema: dict[str, Any] | None = None,
    result_schema: dict[str, Any] | None = None,
) -> ToolRegistryEntry:
    return ToolRegistryEntry(
        tool_id=name,
        name=name,
        version=version,
        description=description,
        tags=tags or [],
        status=status,
        parameters_schema=parameters_schema or {},
        result_schema=result_schema or {},
    )


def _mock_tool_registry(
    tools: list[Any] | None = None,
    entries: list[ToolRegistryEntry] | None = None,
) -> MagicMock:
    reg = MagicMock()
    tools = tools or []
    entries = entries or []
    reg.list_all.return_value = tools
    _entries_map = {e.name: e for e in entries}
    _tools_map = {t.name: t for t in tools}
    reg.get_entry.side_effect = lambda name: _entries_map.get(name)
    reg.get.side_effect = lambda name: _tools_map.get(name)
    reg.list_entries.return_value = entries
    return reg


def _mock_skill_registry(skills: list[dict[str, Any]] | None = None) -> MagicMock:
    reg = MagicMock()
    mock_skills = []
    for s in skills or []:
        skill = MagicMock()
        skill.name = s["name"]
        skill.description = s.get("description", "")
        skill.version = s.get("version", "1.0.0")
        skill.tags = s.get("tags", [])
        skill.status = MagicMock()
        skill.status.value = s.get("status", "active")
        mock_skills.append(skill)
    reg.list_all.return_value = mock_skills
    return reg


def _mock_plugin_registry(
    plugins: list[dict[str, Any]] | None = None,
) -> MagicMock:
    reg = MagicMock()
    plugin_list = plugins or []
    mock_manifests = []
    for p in plugin_list:
        manifest = MagicMock()
        manifest.name = p["name"]
        manifest.version = p.get("version", "1.0.0")
        manifest.tags = p.get("tags", [])
        manifest.contributions = MagicMock()
        manifest.contributions.tools = p.get("tools", [])
        mock_manifests.append(manifest)
    reg.list_all.return_value = mock_manifests

    def _get_state(name: str, *, tenant_id: str = "") -> Any:  # noqa: ARG001
        for plugin in plugin_list:
            if plugin["name"] == name:
                return MagicMock(value=plugin.get("state", "active"))
        return None

    reg.get_state.side_effect = _get_state
    return reg


# ---------------------------------------------------------------------------
# Tests: Aggregation
# ---------------------------------------------------------------------------


class TestAggregation:
    """Catalog aggregates tools from ToolRegistry, SkillRegistry, plugins."""

    def test_empty_registries(self) -> None:
        svc = ToolCatalogService()
        result = svc.list_tools()
        assert result.total == 0
        assert result.tools == []

    def test_aggregates_from_tool_registry(self) -> None:
        shell = _make_tool("shell", "Run shell commands")
        file_ops = _make_tool("file_ops", "File operations")
        reg = _mock_tool_registry(tools=[shell, file_ops])

        svc = ToolCatalogService(tool_registry=reg)
        result = svc.list_tools()

        assert result.total == 2
        names = {t.name for t in result.tools}
        assert names == {"shell", "file_ops"}

    def test_tool_entry_metadata_propagated(self) -> None:
        tool = _make_tool("shell", "Run shell commands")
        entry = _make_entry(
            "shell",
            version="2.1.0",
            tags=["system", "execution"],
            parameters_schema={"type": "object", "properties": {"cmd": {"type": "string"}}},
        )
        reg = _mock_tool_registry(tools=[tool], entries=[entry])

        svc = ToolCatalogService(tool_registry=reg)
        result = svc.list_tools()

        assert result.total == 1
        cat_entry = result.tools[0]
        assert cat_entry.name == "shell"
        assert cat_entry.version == "2.1.0"
        assert cat_entry.has_schema is True
        assert cat_entry.tags == ["system", "execution"]
        assert cat_entry.category == "system"  # first tag becomes category

    def test_yaml_only_entries_included(self) -> None:
        """Entries from YAML definitions without a runtime Tool get included."""
        entry = _make_entry(
            "archived-tool",
            version="0.5.0",
            description="An archived tool",
            status=ToolStatus.DEPRECATED,
        )
        reg = _mock_tool_registry(tools=[], entries=[entry])

        svc = ToolCatalogService(tool_registry=reg)
        result = svc.list_tools()

        assert result.total == 1
        assert result.tools[0].name == "archived-tool"
        assert result.tools[0].provider == ToolProvider.YAML
        assert result.tools[0].enabled is False

    def test_aggregates_skills(self) -> None:
        skill_reg = _mock_skill_registry(
            skills=[
                {"name": "kubernetes-deploy", "description": "K8s deployment", "tags": ["infra"]},
            ]
        )
        svc = ToolCatalogService(skill_registry=skill_reg)
        result = svc.list_tools()

        assert result.total == 1
        assert result.tools[0].name == "skill:kubernetes-deploy"
        assert result.tools[0].provider == ToolProvider.SKILL

    def test_aggregates_plugin_tools(self) -> None:
        plugin_reg = _mock_plugin_registry(
            plugins=[
                {
                    "name": "acme-plugin",
                    "tools": ["acme-lint", "acme-format"],
                    "state": "active",
                },
            ]
        )
        svc = ToolCatalogService(plugin_registry=plugin_reg)
        result = svc.list_tools()

        assert result.total == 2
        names = {t.name for t in result.tools}
        assert "plugin:acme-plugin:acme-lint" in names
        assert "plugin:acme-plugin:acme-format" in names

    def test_plugin_registry_is_tenant_scoped(self) -> None:
        plugin_reg = _mock_plugin_registry(
            plugins=[
                {
                    "name": "tenant-plugin",
                    "tools": ["tenant-tool"],
                    "state": "active",
                },
            ]
        )
        svc = ToolCatalogService(plugin_registry=plugin_reg)

        result = svc.list_tools(tenant_id="tenant-a")

        assert result.total == 1
        plugin_reg.list_all.assert_called_once_with(tenant_id="tenant-a")
        plugin_reg.get_state.assert_called_once_with("tenant-plugin", tenant_id="tenant-a")

    def test_all_sources_combined(self) -> None:
        tool_reg = _mock_tool_registry(tools=[_make_tool("shell")])
        skill_reg = _mock_skill_registry(skills=[{"name": "deploy"}])
        plugin_reg = _mock_plugin_registry(plugins=[{"name": "ext", "tools": ["ext-tool"]}])

        svc = ToolCatalogService(
            tool_registry=tool_reg,
            skill_registry=skill_reg,
            plugin_registry=plugin_reg,
        )
        result = svc.list_tools()

        assert result.total == 3
        providers = {t.provider for t in result.tools}
        assert ToolProvider.BUILTIN in providers
        assert ToolProvider.SKILL in providers
        assert ToolProvider.PLUGIN in providers


# ---------------------------------------------------------------------------
# Tests: Filtering and Search
# ---------------------------------------------------------------------------


class TestFiltering:
    """Filter by category, provider, and text search."""

    def _svc(self) -> ToolCatalogService:
        tools = [_make_tool("shell", "Run commands"), _make_tool("web_fetch", "Fetch URLs")]
        entries = [
            _make_entry("shell", tags=["system"]),
            _make_entry("web_fetch", tags=["network"]),
        ]
        reg = _mock_tool_registry(tools=tools, entries=entries)
        skill_reg = _mock_skill_registry(
            skills=[{"name": "k8s", "tags": ["infra"], "description": "Kubernetes"}]
        )
        return ToolCatalogService(tool_registry=reg, skill_registry=skill_reg)

    def test_filter_by_category(self) -> None:
        result = self._svc().list_tools(category="system")
        assert result.total == 1
        assert result.tools[0].name == "shell"

    def test_filter_by_provider(self) -> None:
        result = self._svc().list_tools(provider="skill")
        assert result.total == 1
        assert result.tools[0].name == "skill:k8s"

    def test_text_search_in_name(self) -> None:
        result = self._svc().list_tools(search="shell")
        assert result.total == 1
        assert result.tools[0].name == "shell"

    def test_text_search_in_description(self) -> None:
        result = self._svc().list_tools(search="kubernetes")
        assert result.total == 1
        assert result.tools[0].name == "skill:k8s"

    def test_text_search_in_tags(self) -> None:
        result = self._svc().list_tools(search="infra")
        assert result.total == 1

    def test_text_search_case_insensitive(self) -> None:
        result = self._svc().list_tools(search="SHELL")
        assert result.total == 1

    def test_no_match(self) -> None:
        result = self._svc().list_tools(search="nonexistent")
        assert result.total == 0


# ---------------------------------------------------------------------------
# Tests: Pagination
# ---------------------------------------------------------------------------


class TestPagination:
    """Verify limit and offset work correctly."""

    def _svc(self) -> ToolCatalogService:
        tools = [_make_tool(f"tool-{i:02d}") for i in range(10)]
        reg = _mock_tool_registry(tools=tools)
        return ToolCatalogService(tool_registry=reg)

    def test_default_returns_all(self) -> None:
        result = self._svc().list_tools()
        assert result.total == 10
        assert len(result.tools) == 10

    def test_limit(self) -> None:
        result = self._svc().list_tools(limit=3)
        assert result.total == 10
        assert len(result.tools) == 3

    def test_offset(self) -> None:
        result = self._svc().list_tools(limit=3, offset=8)
        assert result.total == 10
        assert len(result.tools) == 2  # only 2 left at offset 8

    def test_offset_beyond_total(self) -> None:
        result = self._svc().list_tools(offset=100)
        assert result.total == 10
        assert len(result.tools) == 0


# ---------------------------------------------------------------------------
# Tests: Schema Lookup
# ---------------------------------------------------------------------------


class TestSchemaLookup:
    """get_schema returns parameters schema or None."""

    def test_schema_from_entry(self) -> None:
        schema = {"type": "object", "properties": {"cmd": {"type": "string"}}}
        tool = _make_tool("shell")
        entry = _make_entry("shell", parameters_schema=schema)
        reg = _mock_tool_registry(tools=[tool], entries=[entry])

        svc = ToolCatalogService(tool_registry=reg)
        result = svc.get_schema("shell")

        assert result is not None
        assert result["type"] == "object"
        assert "cmd" in result["properties"]

    def test_schema_not_available(self) -> None:
        tool = _make_tool("basic-tool")
        reg = _mock_tool_registry(tools=[tool])

        svc = ToolCatalogService(tool_registry=reg)
        result = svc.get_schema("basic-tool")

        assert result is None

    def test_schema_not_found_for_missing_tool(self) -> None:
        svc = ToolCatalogService()
        assert svc.get_schema("does-not-exist") is None

    def test_schema_aware_tool_schema_is_included(self) -> None:
        schema = {"type": "object", "properties": {"path": {"type": "string"}}}
        tool = _make_schema_tool("file_ops", schema=schema)
        reg = _mock_tool_registry(tools=[tool])

        svc = ToolCatalogService(tool_registry=reg)
        result = svc.get_tool("file_ops")

        assert result is not None
        assert result.has_schema is True
        assert result.parameters_schema == schema


# ---------------------------------------------------------------------------
# Tests: get_tool
# ---------------------------------------------------------------------------


class TestGetTool:
    """Single tool lookup by name."""

    def test_found(self) -> None:
        tool = _make_tool("shell", "Run commands")
        reg = _mock_tool_registry(tools=[tool])
        svc = ToolCatalogService(tool_registry=reg)

        entry = svc.get_tool("shell")
        assert entry is not None
        assert entry.name == "shell"
        assert entry.description == "Run commands"

    def test_not_found(self) -> None:
        svc = ToolCatalogService()
        assert svc.get_tool("missing") is None


# ---------------------------------------------------------------------------
# Tests: Categories and Providers
# ---------------------------------------------------------------------------


class TestCategoriesAndProviders:
    """list_categories and list_providers return correct counts."""

    def _svc(self) -> ToolCatalogService:
        tools = [_make_tool("a"), _make_tool("b"), _make_tool("c")]
        entries = [
            _make_entry("a", tags=["system"]),
            _make_entry("b", tags=["system"]),
            _make_entry("c", tags=["network"]),
        ]
        reg = _mock_tool_registry(tools=tools, entries=entries)
        skill_reg = _mock_skill_registry(skills=[{"name": "s1"}])
        return ToolCatalogService(tool_registry=reg, skill_registry=skill_reg)

    def test_categories(self) -> None:
        cats = self._svc().list_categories()
        cat_map = {c.category: c.count for c in cats}
        assert cat_map["system"] == 2
        assert cat_map["network"] == 1
        assert cat_map["skill"] == 1

    def test_categories_sorted_by_count_desc(self) -> None:
        cats = self._svc().list_categories()
        assert cats[0].count >= cats[-1].count

    def test_providers(self) -> None:
        provs = self._svc().list_providers()
        prov_map = {p.provider: p.count for p in provs}
        assert prov_map["builtin"] == 3
        assert prov_map["skill"] == 1


# ---------------------------------------------------------------------------
# Tests: Search endpoint
# ---------------------------------------------------------------------------


class TestSearch:
    """Full search with multiple criteria."""

    def _svc(self) -> ToolCatalogService:
        tools = [_make_tool("shell", "Run commands"), _make_tool("web_fetch", "Fetch URLs")]
        entries = [
            _make_entry("shell", tags=["system", "cli"]),
            _make_entry("web_fetch", tags=["network", "http"]),
        ]
        reg = _mock_tool_registry(tools=tools, entries=entries)
        return ToolCatalogService(tool_registry=reg)

    def test_search_by_query(self) -> None:
        result = self._svc().search(CatalogSearchRequest(query="shell"))
        assert result.total == 1
        assert result.tools[0].name == "shell"

    def test_search_by_categories(self) -> None:
        result = self._svc().search(CatalogSearchRequest(categories=["network"]))
        assert result.total == 1
        assert result.tools[0].name == "web_fetch"

    def test_search_by_providers(self) -> None:
        result = self._svc().search(CatalogSearchRequest(providers=["builtin"]))
        assert result.total == 2

    def test_search_by_tags(self) -> None:
        result = self._svc().search(CatalogSearchRequest(tags=["cli"]))
        assert result.total == 1
        assert result.tools[0].name == "shell"

    def test_search_combined_filters(self) -> None:
        result = self._svc().search(CatalogSearchRequest(query="fetch", categories=["network"]))
        assert result.total == 1

    def test_search_with_pagination(self) -> None:
        result = self._svc().search(CatalogSearchRequest(limit=1, offset=0))
        assert result.total == 2
        assert len(result.tools) == 1
        assert result.limit == 1
        assert result.offset == 0
