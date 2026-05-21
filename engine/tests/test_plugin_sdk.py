"""P2.7 Plugin SDK contract tests.

Tests the public extension surface for third-party plugins:
- Manifest validation (name pattern, semver, field constraints)
- Registry allowlist enforcement
- BasePlugin abstract contract
- Registry lifecycle (discover, list, enable, disable)
- Version constraint checking
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from agent33.plugins.base import PluginBase
from agent33.plugins.context import PluginContext
from agent33.plugins.manifest import (
    PluginContributions,
    PluginManifest,
    PluginPermission,
)
from agent33.plugins.models import PluginState
from agent33.plugins.registry import (
    PluginConflictError,
    PluginRegistry,
)
from agent33.plugins.version import parse_version, satisfies_constraint

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manifest(
    name: str = "test-plugin",
    version: str = "1.0.0",
    **overrides: Any,
) -> PluginManifest:
    """Build a PluginManifest with sane defaults, overridable per-test."""
    fields: dict[str, Any] = {
        "name": name,
        "version": version,
        "description": "A test plugin",
        "author": "Test Author",
    }
    fields.update(overrides)
    return PluginManifest(**fields)


def _make_context(plugin_name: str = "test-plugin") -> PluginContext:
    """Build a minimal PluginContext for testing."""
    return PluginContext(
        plugin_name=plugin_name,
        plugin_dir=Path("/tmp/fake-plugin"),
    )


def _make_plugin_dir(tmp_path: Path, name: str = "test-plugin", version: str = "1.0.0") -> Path:
    """Create a minimal plugin directory with a YAML manifest and plugin.py."""
    plugin_dir = tmp_path / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    manifest_content = (
        f"name: {name}\n"
        f'version: "{version}"\n'
        f"description: Test plugin\n"
        f"author: Test\n"
        f"entry_point: plugin:TestPlugin\n"
    )
    (plugin_dir / "plugin.yaml").write_text(manifest_content, encoding="utf-8")
    plugin_code = (
        "from agent33.plugins.base import PluginBase\n"
        "\n"
        "class TestPlugin(PluginBase):\n"
        "    async def on_load(self) -> None:\n"
        "        pass\n"
    )
    (plugin_dir / "plugin.py").write_text(plugin_code, encoding="utf-8")
    return plugin_dir


class ConcretePlugin(PluginBase):
    """Minimal concrete subclass for testing the PluginBase contract."""

    def __init__(self, manifest: PluginManifest, context: PluginContext) -> None:
        super().__init__(manifest, context)
        self.load_called = False
        self.enable_called = False
        self.disable_called = False
        self.unload_called = False

    async def on_load(self) -> None:
        self.load_called = True

    async def on_enable(self) -> None:
        self.enable_called = True

    async def on_disable(self) -> None:
        self.disable_called = True

    async def on_unload(self) -> None:
        self.unload_called = True


# ===================================================================
# Manifest Validation
# ===================================================================


class TestPluginManifestValidation:
    """PluginManifest field-level validation."""

    def test_valid_manifest_accepts_simple_name(self) -> None:
        m = _make_manifest(name="my-plugin")
        assert m.name == "my-plugin"

    def test_valid_manifest_accepts_alphanumeric_dashes(self) -> None:
        m = _make_manifest(name="a-b-c-123")
        assert m.name == "a-b-c-123"

    def test_rejects_name_with_spaces(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            _make_manifest(name="my plugin")
        errors = exc_info.value.errors()
        assert any("pattern" in str(e).lower() or "string_pattern" in e["type"] for e in errors)

    def test_rejects_name_with_uppercase(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            _make_manifest(name="MyPlugin")
        errors = exc_info.value.errors()
        assert any("pattern" in str(e).lower() or "string_pattern" in e["type"] for e in errors)

    def test_rejects_name_starting_with_digit(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            _make_manifest(name="1-invalid")
        errors = exc_info.value.errors()
        assert any("pattern" in str(e).lower() or "string_pattern" in e["type"] for e in errors)

    def test_rejects_name_starting_with_dash(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            _make_manifest(name="-invalid")
        errors = exc_info.value.errors()
        assert any("pattern" in str(e).lower() or "string_pattern" in e["type"] for e in errors)

    def test_rejects_name_with_underscore(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            _make_manifest(name="under_score")
        errors = exc_info.value.errors()
        assert any("pattern" in str(e).lower() or "string_pattern" in e["type"] for e in errors)

    def test_rejects_name_too_long(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            _make_manifest(name="a" * 65)
        errors = exc_info.value.errors()
        assert any(
            "max_length" in e["type"] or "too_long" in e["type"] or "string_too_long" in e["type"]
            for e in errors
        )

    def test_rejects_empty_name(self) -> None:
        with pytest.raises(ValidationError):
            _make_manifest(name="")

    def test_rejects_invalid_semver_missing_patch(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            _make_manifest(version="1.0")
        errors = exc_info.value.errors()
        assert any("pattern" in str(e).lower() or "string_pattern" in e["type"] for e in errors)

    def test_rejects_invalid_semver_with_prefix(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            _make_manifest(version="v1.0.0")
        errors = exc_info.value.errors()
        assert any("pattern" in str(e).lower() or "string_pattern" in e["type"] for e in errors)

    def test_rejects_invalid_semver_non_numeric(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            _make_manifest(version="one.two.three")
        errors = exc_info.value.errors()
        assert any("pattern" in str(e).lower() or "string_pattern" in e["type"] for e in errors)

    def test_accepts_valid_semver(self) -> None:
        m = _make_manifest(version="2.10.3")
        assert m.version == "2.10.3"

    def test_description_truncated_at_max(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            _make_manifest(description="x" * 501)
        errors = exc_info.value.errors()
        assert any(
            "max_length" in e["type"] or "too_long" in e["type"] or "string_too_long" in e["type"]
            for e in errors
        )

    def test_manifest_default_entry_point(self) -> None:
        m = _make_manifest()
        assert m.entry_point == "plugin:Plugin"

    def test_manifest_custom_entry_point(self) -> None:
        m = _make_manifest(entry_point="mymod:MyClass")
        assert m.entry_point == "mymod:MyClass"

    def test_manifest_permissions_enum_values(self) -> None:
        m = _make_manifest(permissions=[PluginPermission.FILE_READ, PluginPermission.NETWORK])
        assert PluginPermission.FILE_READ in m.permissions
        assert PluginPermission.NETWORK in m.permissions
        assert len(m.permissions) == 2

    def test_manifest_contributions_default_empty(self) -> None:
        m = _make_manifest()
        assert m.contributions.skills == []
        assert m.contributions.tools == []
        assert m.contributions.agents == []
        assert m.contributions.hooks == []

    def test_manifest_contributions_populated(self) -> None:
        m = _make_manifest(
            contributions=PluginContributions(
                skills=["skill-a"],
                tools=["ToolA"],
                hooks=["HookA"],
            )
        )
        assert m.contributions.skills == ["skill-a"]
        assert m.contributions.tools == ["ToolA"]
        assert m.contributions.hooks == ["HookA"]


# ===================================================================
# Registry Allowlist
# ===================================================================


class TestPluginRegistryAllowlist:
    """Registry allowlist enforcement."""

    def test_no_allowlist_allows_everything(self) -> None:
        registry = PluginRegistry()
        assert registry.is_allowed("any-name") is True
        assert registry.is_allowed("another-one") is True

    def test_empty_allowlist_allows_everything(self) -> None:
        registry = PluginRegistry(allowlist=[])
        assert registry.is_allowed("any-name") is True

    def test_allowlist_allows_listed_plugin(self) -> None:
        registry = PluginRegistry(allowlist=["approved-plugin", "another-approved"])
        assert registry.is_allowed("approved-plugin") is True
        assert registry.is_allowed("another-approved") is True

    def test_allowlist_rejects_unlisted_plugin(self) -> None:
        registry = PluginRegistry(allowlist=["approved-plugin"])
        assert registry.is_allowed("not-approved") is False

    def test_discover_plugin_rejects_unlisted_name(self, tmp_path: Path) -> None:
        """discover_plugin raises PermissionError for plugins not on the allowlist."""
        registry = PluginRegistry(allowlist=["other-plugin"])
        plugin_dir = _make_plugin_dir(tmp_path, name="rejected-plugin")

        with pytest.raises(PermissionError, match="not on the plugin allowlist"):
            registry.discover_plugin(plugin_dir)

        # Plugin should NOT be in the registry
        assert registry.get("rejected-plugin") is None
        assert registry.count == 0

    def test_discover_plugin_accepts_listed_name(self, tmp_path: Path) -> None:
        """discover_plugin succeeds for plugins on the allowlist."""
        registry = PluginRegistry(allowlist=["accepted-plugin"])
        plugin_dir = _make_plugin_dir(tmp_path, name="accepted-plugin")

        manifest = registry.discover_plugin(plugin_dir)

        assert manifest.name == "accepted-plugin"
        assert registry.count == 1

    def test_discover_plugin_no_allowlist_accepts_all(self, tmp_path: Path) -> None:
        """Without an allowlist, any valid plugin is accepted."""
        registry = PluginRegistry()
        plugin_dir = _make_plugin_dir(tmp_path, name="any-plugin")

        manifest = registry.discover_plugin(plugin_dir)

        assert manifest.name == "any-plugin"
        assert registry.count == 1


# ===================================================================
# PluginBase Contract
# ===================================================================


class TestPluginBaseContract:
    """PluginBase abstract interface and lifecycle."""

    def test_concrete_plugin_has_manifest_properties(self) -> None:
        manifest = _make_manifest(name="test-plugin", version="2.0.0")
        context = _make_context("test-plugin")
        plugin = ConcretePlugin(manifest, context)

        assert plugin.name == "test-plugin"
        assert plugin.version == "2.0.0"
        assert plugin.manifest is manifest
        assert plugin.context is context

    async def test_lifecycle_methods_are_called(self) -> None:
        manifest = _make_manifest()
        context = _make_context()
        plugin = ConcretePlugin(manifest, context)

        assert plugin.load_called is False
        await plugin.on_load()
        assert plugin.load_called is True

        assert plugin.enable_called is False
        await plugin.on_enable()
        assert plugin.enable_called is True

        assert plugin.disable_called is False
        await plugin.on_disable()
        assert plugin.disable_called is True

        assert plugin.unload_called is False
        await plugin.on_unload()
        assert plugin.unload_called is True

    async def test_default_lifecycle_methods_are_noop(self) -> None:
        """PluginBase lifecycle defaults do nothing (no exceptions)."""

        class MinimalPlugin(PluginBase):
            """Plugin that overrides nothing."""

        manifest = _make_manifest()
        context = _make_context()
        plugin = MinimalPlugin(manifest, context)

        # All lifecycle methods should succeed silently
        await plugin.on_load()
        await plugin.on_enable()
        await plugin.on_disable()
        await plugin.on_unload()

    def test_register_skill_rejects_undeclared(self) -> None:
        """register_skill raises ValueError for skills not in contributions."""
        from agent33.skills.definition import SkillDefinition

        manifest = _make_manifest(contributions=PluginContributions(skills=["declared-skill"]))
        context = _make_context()
        plugin = ConcretePlugin(manifest, context)

        skill = SkillDefinition(name="undeclared-skill")
        with pytest.raises(ValueError, match="undeclared skill"):
            plugin.register_skill(skill)

    def test_register_skill_rejects_wrong_type(self) -> None:
        """register_skill raises TypeError for non-SkillDefinition objects."""
        manifest = _make_manifest()
        context = _make_context()
        plugin = ConcretePlugin(manifest, context)

        with pytest.raises(TypeError, match="Expected SkillDefinition"):
            plugin.register_skill("not a skill")  # type: ignore[arg-type]

    def test_register_tool_rejects_undeclared(self) -> None:
        """register_tool raises ValueError for tools not in contributions."""
        from agent33.tools.base import Tool, ToolContext, ToolResult

        manifest = _make_manifest(contributions=PluginContributions(tools=["OtherTool"]))
        context = _make_context()
        plugin = ConcretePlugin(manifest, context)

        class UndeclaredTool(Tool):
            name = "undeclared"
            description = "test"

            async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
                return ToolResult.ok({})

        with pytest.raises(ValueError, match="undeclared tool"):
            plugin.register_tool(UndeclaredTool())

    def test_register_hook_rejects_without_permission(self) -> None:
        """register_hook raises PermissionError without hook:register permission."""
        manifest = _make_manifest(permissions=[])  # no hook permission
        context = _make_context()
        plugin = ConcretePlugin(manifest, context)

        class FakeHook:
            pass

        with pytest.raises(PermissionError, match="lacks hook:register"):
            plugin.register_hook(FakeHook())


# ===================================================================
# Registry Discovery and CRUD
# ===================================================================


class TestPluginRegistryCRUD:
    """Registry discovery, listing, and state management."""

    def test_discover_returns_count(self, tmp_path: Path) -> None:
        _make_plugin_dir(tmp_path, name="plugin-a")
        _make_plugin_dir(tmp_path, name="plugin-b")

        registry = PluginRegistry()
        count = registry.discover(tmp_path)

        assert count == 2
        assert registry.count == 2

    def test_discover_nonexistent_directory_returns_zero(self, tmp_path: Path) -> None:
        registry = PluginRegistry()
        count = registry.discover(tmp_path / "nonexistent")
        assert count == 0

    def test_discover_plugin_conflict_raises(self, tmp_path: Path) -> None:
        """Discovering the same plugin name twice raises PluginConflictError."""
        dir_a = tmp_path / "first"
        dir_b = tmp_path / "second"
        _make_plugin_dir(dir_a, name="conflict-plugin")
        _make_plugin_dir(dir_b, name="conflict-plugin")

        registry = PluginRegistry()
        registry.discover_plugin(dir_a / "conflict-plugin")

        with pytest.raises(PluginConflictError, match="already discovered"):
            registry.discover_plugin(dir_b / "conflict-plugin")

    def test_get_returns_none_for_unknown(self) -> None:
        registry = PluginRegistry()
        assert registry.get("nonexistent") is None

    def test_get_returns_entry_after_discover(self, tmp_path: Path) -> None:
        plugin_dir = _make_plugin_dir(tmp_path, name="found-plugin")
        registry = PluginRegistry()
        registry.discover_plugin(plugin_dir)

        entry = registry.get("found-plugin")
        assert entry is not None
        assert entry.manifest.name == "found-plugin"
        assert entry.state == PluginState.DISCOVERED

    def test_list_all_returns_manifests_sorted(self, tmp_path: Path) -> None:
        _make_plugin_dir(tmp_path, name="z-plugin")
        _make_plugin_dir(tmp_path, name="a-plugin")
        _make_plugin_dir(tmp_path, name="m-plugin")

        registry = PluginRegistry()
        registry.discover(tmp_path)

        manifests = registry.list_all()
        names = [m.name for m in manifests]
        assert names == ["a-plugin", "m-plugin", "z-plugin"]

    def test_remove_discovered_plugin(self, tmp_path: Path) -> None:
        plugin_dir = _make_plugin_dir(tmp_path, name="removable")
        registry = PluginRegistry()
        registry.discover_plugin(plugin_dir)

        assert registry.count == 1
        removed = registry.remove("removable")
        assert removed is True
        assert registry.count == 0

    def test_remove_nonexistent_returns_false(self) -> None:
        registry = PluginRegistry()
        assert registry.remove("nonexistent") is False

    def test_search_by_name(self, tmp_path: Path) -> None:
        _make_plugin_dir(tmp_path, name="data-processor")
        _make_plugin_dir(tmp_path, name="web-scraper")

        registry = PluginRegistry()
        registry.discover(tmp_path)

        results = registry.search("data")
        assert len(results) == 1
        assert results[0].name == "data-processor"

    def test_find_by_tag(self, tmp_path: Path) -> None:
        """find_by_tag returns plugins with the specified tag."""
        plugin_dir = _make_plugin_dir(tmp_path, name="tagged-plugin")
        # Overwrite manifest with tags
        manifest_content = (
            "name: tagged-plugin\n"
            'version: "1.0.0"\n'
            "description: A tagged plugin\n"
            "author: Test\n"
            "entry_point: plugin:TestPlugin\n"
            "tags:\n"
            "  - analytics\n"
            "  - data\n"
        )
        (plugin_dir / "plugin.yaml").write_text(manifest_content, encoding="utf-8")

        registry = PluginRegistry()
        registry.discover_plugin(plugin_dir)

        results = registry.find_by_tag("analytics")
        assert len(results) == 1
        assert results[0].name == "tagged-plugin"

        assert registry.find_by_tag("nonexistent") == []


# ===================================================================
# Version Constraint Checking
# ===================================================================


class TestVersionConstraints:
    """SemVer parsing and constraint satisfaction."""

    def test_parse_version_valid(self) -> None:
        assert parse_version("1.2.3") == (1, 2, 3)
        assert parse_version("0.0.0") == (0, 0, 0)
        assert parse_version("99.88.77") == (99, 88, 77)

    def test_parse_version_invalid_format(self) -> None:
        with pytest.raises(ValueError, match="Invalid SemVer"):
            parse_version("1.2")

    def test_parse_version_non_integer(self) -> None:
        with pytest.raises(ValueError, match="non-integer"):
            parse_version("1.two.3")

    def test_wildcard_matches_anything(self) -> None:
        assert satisfies_constraint("1.0.0", "*") is True
        assert satisfies_constraint("99.99.99", "*") is True

    def test_exact_match(self) -> None:
        assert satisfies_constraint("1.2.3", "1.2.3") is True
        assert satisfies_constraint("1.2.3", "1.2.4") is False

    def test_greater_or_equal(self) -> None:
        assert satisfies_constraint("2.0.0", ">=1.0.0") is True
        assert satisfies_constraint("1.0.0", ">=1.0.0") is True
        assert satisfies_constraint("0.9.9", ">=1.0.0") is False

    def test_less_or_equal(self) -> None:
        assert satisfies_constraint("1.0.0", "<=2.0.0") is True
        assert satisfies_constraint("2.0.0", "<=2.0.0") is True
        assert satisfies_constraint("2.0.1", "<=2.0.0") is False

    def test_strictly_greater(self) -> None:
        assert satisfies_constraint("1.0.1", ">1.0.0") is True
        assert satisfies_constraint("1.0.0", ">1.0.0") is False

    def test_strictly_less(self) -> None:
        assert satisfies_constraint("0.9.9", "<1.0.0") is True
        assert satisfies_constraint("1.0.0", "<1.0.0") is False

    def test_caret_compatible(self) -> None:
        # Same major, >= minor.patch
        assert satisfies_constraint("1.2.3", "^1.0.0") is True
        assert satisfies_constraint("1.0.0", "^1.0.0") is True
        assert satisfies_constraint("2.0.0", "^1.0.0") is False  # different major

    def test_tilde_approximate(self) -> None:
        # Same major.minor, >= patch
        assert satisfies_constraint("1.2.5", "~1.2.3") is True
        assert satisfies_constraint("1.2.3", "~1.2.3") is True
        assert satisfies_constraint("1.2.2", "~1.2.3") is False
        assert satisfies_constraint("1.3.0", "~1.2.3") is False  # different minor

    def test_registry_version_constraint_check(self, tmp_path: Path) -> None:
        """Registry detects version constraint violations between plugins."""
        # Create plugin-a v1.0.0 that depends on plugin-b >=2.0.0
        dir_a = tmp_path / "plugin-a"
        dir_a.mkdir()
        (dir_a / "plugin.yaml").write_text(
            "name: plugin-a\n"
            'version: "1.0.0"\n'
            "description: Plugin A\n"
            "author: Test\n"
            "entry_point: plugin:TestPlugin\n"
            "dependencies:\n"
            "  - name: plugin-b\n"
            '    version_constraint: ">=2.0.0"\n',
            encoding="utf-8",
        )
        (dir_a / "plugin.py").write_text(
            "from agent33.plugins.base import PluginBase\nclass TestPlugin(PluginBase): pass\n",
            encoding="utf-8",
        )

        # Create plugin-b v1.5.0 (does NOT satisfy >=2.0.0)
        _make_plugin_dir(tmp_path, name="plugin-b", version="1.5.0")

        registry = PluginRegistry()
        registry.discover(tmp_path)

        violations = registry.check_version_constraints()
        assert len(violations) == 1
        assert "plugin-a" in violations[0]
        assert "plugin-b" in violations[0]
        assert ">=2.0.0" in violations[0]


# ===================================================================
# Registry Lifecycle (async)
# ===================================================================


class TestPluginRegistryLifecycle:
    """Async lifecycle operations: load, enable, disable, unload."""

    async def test_load_and_enable_plugin(self, tmp_path: Path) -> None:
        """Full lifecycle: discover -> load -> enable -> active state."""
        plugin_dir = _make_plugin_dir(tmp_path, name="lifecycle-plugin")
        registry = PluginRegistry()
        registry.discover_plugin(plugin_dir)

        assert registry.get_state("lifecycle-plugin") == PluginState.DISCOVERED

        # Build a minimal context factory
        def ctx_factory(manifest: Any, pdir: Path) -> PluginContext:
            return PluginContext(plugin_name=manifest.name, plugin_dir=pdir)

        await registry.load("lifecycle-plugin", ctx_factory)
        assert registry.get_state("lifecycle-plugin") == PluginState.LOADED

        await registry.enable("lifecycle-plugin")
        assert registry.get_state("lifecycle-plugin") == PluginState.ACTIVE
        assert registry.active_count == 1

    async def test_disable_active_plugin(self, tmp_path: Path) -> None:
        plugin_dir = _make_plugin_dir(tmp_path, name="disable-me")
        registry = PluginRegistry()
        registry.discover_plugin(plugin_dir)

        def ctx_factory(manifest: Any, pdir: Path) -> PluginContext:
            return PluginContext(plugin_name=manifest.name, plugin_dir=pdir)

        await registry.load("disable-me", ctx_factory)
        await registry.enable("disable-me")
        assert registry.get_state("disable-me") == PluginState.ACTIVE

        await registry.disable("disable-me")
        assert registry.get_state("disable-me") == PluginState.DISABLED
        assert registry.active_count == 0

    async def test_unload_removes_instance(self, tmp_path: Path) -> None:
        plugin_dir = _make_plugin_dir(tmp_path, name="unload-me")
        registry = PluginRegistry()
        registry.discover_plugin(plugin_dir)

        def ctx_factory(manifest: Any, pdir: Path) -> PluginContext:
            return PluginContext(plugin_name=manifest.name, plugin_dir=pdir)

        await registry.load("unload-me", ctx_factory)
        await registry.enable("unload-me")
        await registry.unload("unload-me")

        entry = registry.get("unload-me")
        assert entry is not None
        assert entry.state == PluginState.UNLOADED
        assert entry.instance is None

    async def test_enable_not_loaded_raises(self, tmp_path: Path) -> None:
        """Cannot enable a plugin that has not been loaded."""
        plugin_dir = _make_plugin_dir(tmp_path, name="not-loaded")
        registry = PluginRegistry()
        registry.discover_plugin(plugin_dir)

        with pytest.raises(RuntimeError, match="Cannot enable"):
            await registry.enable("not-loaded")

    async def test_load_all_respects_dependency_order(self, tmp_path: Path) -> None:
        """load_all loads plugins in topological order."""
        # plugin-b depends on plugin-a
        dir_a = tmp_path / "plugin-a"
        dir_a.mkdir()
        (dir_a / "plugin.yaml").write_text(
            'name: plugin-a\nversion: "1.0.0"\n'
            "description: Base\nauthor: Test\nentry_point: plugin:TestPlugin\n",
            encoding="utf-8",
        )
        (dir_a / "plugin.py").write_text(
            "from agent33.plugins.base import PluginBase\nclass TestPlugin(PluginBase): pass\n",
            encoding="utf-8",
        )

        dir_b = tmp_path / "plugin-b"
        dir_b.mkdir()
        (dir_b / "plugin.yaml").write_text(
            'name: plugin-b\nversion: "1.0.0"\n'
            "description: Depends on A\nauthor: Test\nentry_point: plugin:TestPlugin\n"
            'dependencies:\n  - name: plugin-a\n    version_constraint: "*"\n',
            encoding="utf-8",
        )
        (dir_b / "plugin.py").write_text(
            "from agent33.plugins.base import PluginBase\nclass TestPlugin(PluginBase): pass\n",
            encoding="utf-8",
        )

        registry = PluginRegistry()
        registry.discover(tmp_path)

        load_order = registry.resolve_load_order()
        # plugin-a must come before plugin-b
        assert load_order.index("plugin-a") < load_order.index("plugin-b")

        def ctx_factory(manifest: Any, pdir: Path) -> PluginContext:
            return PluginContext(plugin_name=manifest.name, plugin_dir=pdir)

        loaded = await registry.load_all(ctx_factory)
        assert loaded == 2
        assert registry.get_state("plugin-a") == PluginState.LOADED
        assert registry.get_state("plugin-b") == PluginState.LOADED

    async def test_list_active_returns_only_active(self, tmp_path: Path) -> None:
        _make_plugin_dir(tmp_path, name="active-one")
        _make_plugin_dir(tmp_path, name="not-active")

        registry = PluginRegistry()
        registry.discover(tmp_path)

        def ctx_factory(manifest: Any, pdir: Path) -> PluginContext:
            return PluginContext(plugin_name=manifest.name, plugin_dir=pdir)

        await registry.load_all(ctx_factory)
        await registry.enable("active-one")

        active = registry.list_active()
        assert len(active) == 1
        assert active[0].name == "active-one"
