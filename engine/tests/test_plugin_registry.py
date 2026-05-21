"""Tests for PluginRegistry: discovery, dependency resolution, lifecycle, CRUD, search."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from agent33.plugins.context import PluginContext
from agent33.plugins.models import PluginState
from agent33.plugins.registry import (
    CyclicDependencyError,
    PluginDependencyError,
    PluginRegistry,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agent33.plugins.manifest import PluginManifest


def _write_yaml_manifest(plugin_dir: Path, name: str, **kwargs: Any) -> None:
    """Write a minimal plugin.yaml manifest."""
    plugin_dir.mkdir(parents=True, exist_ok=True)
    deps = kwargs.pop("dependencies", None)
    tags = kwargs.pop("tags", None)

    yaml_content = f"name: {name}\nversion: {kwargs.get('version', '1.0.0')}\n"
    if "description" in kwargs:
        yaml_content += f"description: {kwargs['description']}\n"
    if deps:
        yaml_content += "dependencies:\n"
        for dep in deps:
            yaml_content += f"  - name: {dep['name']}\n"
            if "version_constraint" in dep:
                yaml_content += f'    version_constraint: "{dep["version_constraint"]}"\n'
            if dep.get("optional"):
                yaml_content += "    optional: true\n"
    if tags:
        yaml_content += "tags:\n"
        for tag in tags:
            yaml_content += f"  - {tag}\n"
    if "contributions" in kwargs:
        yaml_content += "contributions:\n"
        for ctype, items in kwargs["contributions"].items():
            yaml_content += f"  {ctype}:\n"
            for item in items:
                yaml_content += f"    - {item}\n"

    (plugin_dir / "plugin.yaml").write_text(yaml_content, encoding="utf-8")


def _make_context_factory() -> Any:
    """Create a mock context factory for testing."""

    def factory(manifest: PluginManifest, plugin_dir: Path) -> PluginContext:
        return PluginContext(
            plugin_name=manifest.name,
            plugin_dir=plugin_dir,
            granted_permissions=frozenset(),
            skill_registry=MagicMock(),
            tool_registry=MagicMock(),
        )

    return factory


class TestPluginDiscovery:
    """Tests for PluginRegistry.discover()."""

    def test_discover_empty_directory(self, tmp_path) -> None:
        registry = PluginRegistry()
        count = registry.discover(tmp_path)
        assert count == 0
        assert registry.count == 0

    def test_discover_nonexistent_directory(self, tmp_path) -> None:
        registry = PluginRegistry()
        count = registry.discover(tmp_path / "nonexistent")
        assert count == 0

    def test_discover_single_plugin(self, tmp_path) -> None:
        _write_yaml_manifest(tmp_path / "hello", "hello")
        registry = PluginRegistry()
        count = registry.discover(tmp_path)
        assert count == 1
        assert registry.count == 1
        assert registry.get_manifest("hello") is not None

    def test_discover_multiple_plugins(self, tmp_path) -> None:
        _write_yaml_manifest(tmp_path / "alpha", "alpha")
        _write_yaml_manifest(tmp_path / "beta", "beta")
        _write_yaml_manifest(tmp_path / "gamma", "gamma")
        registry = PluginRegistry()
        count = registry.discover(tmp_path)
        assert count == 3
        assert registry.count == 3

    def test_discover_skips_non_directory_files(self, tmp_path) -> None:
        _write_yaml_manifest(tmp_path / "hello", "hello")
        (tmp_path / "readme.txt").write_text("not a plugin", encoding="utf-8")
        registry = PluginRegistry()
        count = registry.discover(tmp_path)
        assert count == 1

    def test_discover_skips_directories_without_manifest(self, tmp_path) -> None:
        _write_yaml_manifest(tmp_path / "valid", "valid")
        (tmp_path / "no-manifest").mkdir()
        registry = PluginRegistry()
        count = registry.discover(tmp_path)
        assert count == 1

    def test_discover_skips_duplicate_names(self, tmp_path) -> None:
        """Second directory with same plugin name is skipped."""
        _write_yaml_manifest(tmp_path / "aaa-first", "same-name", version="1.0.0")
        _write_yaml_manifest(tmp_path / "bbb-second", "same-name", version="2.0.0")
        registry = PluginRegistry()
        count = registry.discover(tmp_path)
        assert count == 1
        # First discovered (alphabetical) wins
        manifest = registry.get_manifest("same-name")
        assert manifest is not None
        assert manifest.version == "1.0.0"

    def test_discover_sets_state_to_discovered(self, tmp_path) -> None:
        _write_yaml_manifest(tmp_path / "hello", "hello")
        registry = PluginRegistry()
        registry.discover(tmp_path)
        assert registry.get_state("hello") == PluginState.DISCOVERED


class TestDependencyResolution:
    """Tests for PluginRegistry.resolve_load_order() using Kahn's algorithm."""

    def test_no_dependencies_returns_alphabetical(self, tmp_path) -> None:
        _write_yaml_manifest(tmp_path / "charlie", "charlie")
        _write_yaml_manifest(tmp_path / "alpha", "alpha")
        _write_yaml_manifest(tmp_path / "bravo", "bravo")
        registry = PluginRegistry()
        registry.discover(tmp_path)
        order = registry.resolve_load_order()
        # All have in-degree 0 so processed in alphabetical order (sorted iterdir)
        assert set(order) == {"alpha", "bravo", "charlie"}

    def test_linear_dependency_chain(self, tmp_path) -> None:
        """A -> B -> C (C loads first, then B, then A)."""
        _write_yaml_manifest(
            tmp_path / "plugin-a",
            "plugin-a",
            dependencies=[{"name": "plugin-b"}],
        )
        _write_yaml_manifest(
            tmp_path / "plugin-b",
            "plugin-b",
            dependencies=[{"name": "plugin-c"}],
        )
        _write_yaml_manifest(tmp_path / "plugin-c", "plugin-c")
        registry = PluginRegistry()
        registry.discover(tmp_path)
        order = registry.resolve_load_order()

        # C must come before B, B before A
        assert order.index("plugin-c") < order.index("plugin-b")
        assert order.index("plugin-b") < order.index("plugin-a")

    def test_diamond_dependency(self, tmp_path) -> None:
        """A depends on B and C, both depend on D."""
        _write_yaml_manifest(
            tmp_path / "plugin-a",
            "plugin-a",
            dependencies=[{"name": "plugin-b"}, {"name": "plugin-c"}],
        )
        _write_yaml_manifest(
            tmp_path / "plugin-b",
            "plugin-b",
            dependencies=[{"name": "plugin-d"}],
        )
        _write_yaml_manifest(
            tmp_path / "plugin-c",
            "plugin-c",
            dependencies=[{"name": "plugin-d"}],
        )
        _write_yaml_manifest(tmp_path / "plugin-d", "plugin-d")
        registry = PluginRegistry()
        registry.discover(tmp_path)
        order = registry.resolve_load_order()

        assert order.index("plugin-d") < order.index("plugin-b")
        assert order.index("plugin-d") < order.index("plugin-c")
        assert order.index("plugin-b") < order.index("plugin-a")
        assert order.index("plugin-c") < order.index("plugin-a")

    def test_cyclic_dependency_raises(self, tmp_path) -> None:
        """A -> B -> A raises CyclicDependencyError."""
        _write_yaml_manifest(
            tmp_path / "plugin-a",
            "plugin-a",
            dependencies=[{"name": "plugin-b"}],
        )
        _write_yaml_manifest(
            tmp_path / "plugin-b",
            "plugin-b",
            dependencies=[{"name": "plugin-a"}],
        )
        registry = PluginRegistry()
        registry.discover(tmp_path)
        with pytest.raises(CyclicDependencyError) as exc_info:
            registry.resolve_load_order()
        assert len(exc_info.value.cycle) > 0

    def test_missing_required_dependency_raises(self, tmp_path) -> None:
        _write_yaml_manifest(
            tmp_path / "plugin-a",
            "plugin-a",
            dependencies=[{"name": "missing-plugin"}],
        )
        registry = PluginRegistry()
        registry.discover(tmp_path)
        with pytest.raises(PluginDependencyError, match="missing-plugin"):
            registry.resolve_load_order()

    def test_missing_optional_dependency_ok(self, tmp_path) -> None:
        _write_yaml_manifest(
            tmp_path / "plugin-a",
            "plugin-a",
            dependencies=[{"name": "optional-plugin", "optional": True}],
        )
        registry = PluginRegistry()
        registry.discover(tmp_path)
        order = registry.resolve_load_order()
        assert order == ["plugin-a"]


class TestVersionConstraints:
    """Tests for PluginRegistry.check_version_constraints()."""

    def test_no_violations_when_constraints_met(self, tmp_path) -> None:
        _write_yaml_manifest(
            tmp_path / "consumer",
            "consumer",
            dependencies=[{"name": "provider", "version_constraint": ">=1.0.0"}],
        )
        _write_yaml_manifest(tmp_path / "provider", "provider", version="1.2.0")
        registry = PluginRegistry()
        registry.discover(tmp_path)
        violations = registry.check_version_constraints()
        assert violations == []

    def test_violation_when_version_too_low(self, tmp_path) -> None:
        _write_yaml_manifest(
            tmp_path / "consumer",
            "consumer",
            dependencies=[{"name": "provider", "version_constraint": ">=2.0.0"}],
        )
        _write_yaml_manifest(tmp_path / "provider", "provider", version="1.0.0")
        registry = PluginRegistry()
        registry.discover(tmp_path)
        violations = registry.check_version_constraints()
        assert len(violations) == 1
        assert ">=2.0.0" in violations[0]

    def test_wildcard_constraint_always_passes(self, tmp_path) -> None:
        _write_yaml_manifest(
            tmp_path / "consumer",
            "consumer",
            dependencies=[{"name": "provider", "version_constraint": "*"}],
        )
        _write_yaml_manifest(tmp_path / "provider", "provider", version="0.0.1")
        registry = PluginRegistry()
        registry.discover(tmp_path)
        violations = registry.check_version_constraints()
        assert violations == []

    def test_missing_required_dep_is_violation(self, tmp_path) -> None:
        _write_yaml_manifest(
            tmp_path / "consumer",
            "consumer",
            dependencies=[{"name": "missing-dep"}],
        )
        registry = PluginRegistry()
        registry.discover(tmp_path)
        violations = registry.check_version_constraints()
        assert len(violations) == 1
        assert "missing" in violations[0].lower()


class TestPluginLoading:
    """Tests for PluginRegistry.load() and load_all()."""

    async def test_load_transitions_to_loaded(self, tmp_path) -> None:
        """Loading a plugin transitions state from DISCOVERED to LOADED."""
        _write_yaml_manifest(tmp_path / "test-plugin", "test-plugin")

        # Write a simple plugin module
        (tmp_path / "test-plugin" / "plugin.py").write_text(
            """\
from agent33.plugins.base import PluginBase

class Plugin(PluginBase):
    async def on_load(self):
        pass
""",
            encoding="utf-8",
        )

        registry = PluginRegistry()
        registry.discover(tmp_path)
        context_factory = _make_context_factory()

        await registry.load("test-plugin", context_factory)
        assert registry.get_state("test-plugin") == PluginState.LOADED
        entry = registry.get("test-plugin")
        assert entry is not None
        assert entry.instance is not None

    async def test_load_nonexistent_plugin_raises(self) -> None:
        registry = PluginRegistry()
        with pytest.raises(KeyError, match="not discovered"):
            await registry.load("ghost", _make_context_factory())

    async def test_load_error_sets_error_state(self, tmp_path) -> None:
        _write_yaml_manifest(
            tmp_path / "bad-plugin",
            "bad-plugin",
            # Entry point module does not exist
        )
        (tmp_path / "bad-plugin" / "plugin.py").write_text(
            "raise ImportError('broken')\n", encoding="utf-8"
        )

        registry = PluginRegistry()
        registry.discover(tmp_path)

        with pytest.raises(ImportError):
            await registry.load("bad-plugin", _make_context_factory())

        assert registry.get_state("bad-plugin") == PluginState.ERROR
        entry = registry.get("bad-plugin")
        assert entry is not None
        assert entry.error is not None

    async def test_load_all_loads_in_dependency_order(self, tmp_path) -> None:
        """load_all loads all discovered plugins in topological order."""
        _write_yaml_manifest(tmp_path / "base-plugin", "base-plugin")
        (tmp_path / "base-plugin" / "plugin.py").write_text(
            "from agent33.plugins.base import PluginBase\n\n"
            "class Plugin(PluginBase):\n"
            "    async def on_load(self): pass\n",
            encoding="utf-8",
        )

        registry = PluginRegistry()
        registry.discover(tmp_path)
        loaded = await registry.load_all(_make_context_factory())
        assert loaded == 1
        assert registry.get_state("base-plugin") == PluginState.LOADED


class TestPluginEnableDisable:
    """Tests for enable/disable lifecycle transitions."""

    async def _setup_loaded_plugin(self, tmp_path) -> PluginRegistry:
        """Create and load a simple plugin."""
        _write_yaml_manifest(tmp_path / "test-plugin", "test-plugin")
        (tmp_path / "test-plugin" / "plugin.py").write_text(
            "from agent33.plugins.base import PluginBase\n\n"
            "class Plugin(PluginBase):\n"
            "    async def on_load(self): pass\n"
            "    async def on_enable(self): pass\n"
            "    async def on_disable(self): pass\n"
            "    async def on_unload(self): pass\n",
            encoding="utf-8",
        )
        registry = PluginRegistry()
        registry.discover(tmp_path)
        await registry.load("test-plugin", _make_context_factory())
        return registry

    async def test_enable_loaded_plugin(self, tmp_path) -> None:
        registry = await self._setup_loaded_plugin(tmp_path)
        await registry.enable("test-plugin")
        assert registry.get_state("test-plugin") == PluginState.ACTIVE

    async def test_enable_discovered_plugin_raises(self, tmp_path) -> None:
        _write_yaml_manifest(tmp_path / "test-plugin", "test-plugin")
        registry = PluginRegistry()
        registry.discover(tmp_path)
        with pytest.raises(RuntimeError, match="Must be LOADED or DISABLED"):
            await registry.enable("test-plugin")

    async def test_disable_active_plugin(self, tmp_path) -> None:
        registry = await self._setup_loaded_plugin(tmp_path)
        await registry.enable("test-plugin")
        await registry.disable("test-plugin")
        assert registry.get_state("test-plugin") == PluginState.DISABLED

    async def test_disable_non_active_raises(self, tmp_path) -> None:
        registry = await self._setup_loaded_plugin(tmp_path)
        # Plugin is LOADED, not ACTIVE
        with pytest.raises(RuntimeError, match="Must be ACTIVE"):
            await registry.disable("test-plugin")

    async def test_re_enable_disabled_plugin(self, tmp_path) -> None:
        registry = await self._setup_loaded_plugin(tmp_path)
        await registry.enable("test-plugin")
        await registry.disable("test-plugin")
        await registry.enable("test-plugin")
        assert registry.get_state("test-plugin") == PluginState.ACTIVE


class TestPluginUnloading:
    """Tests for unload lifecycle."""

    async def _setup_active_plugin(self, tmp_path) -> PluginRegistry:
        _write_yaml_manifest(tmp_path / "test-plugin", "test-plugin")
        (tmp_path / "test-plugin" / "plugin.py").write_text(
            "from agent33.plugins.base import PluginBase\n\n"
            "class Plugin(PluginBase):\n"
            "    async def on_load(self): pass\n"
            "    async def on_enable(self): pass\n"
            "    async def on_disable(self): pass\n"
            "    async def on_unload(self): pass\n",
            encoding="utf-8",
        )
        registry = PluginRegistry()
        registry.discover(tmp_path)
        await registry.load("test-plugin", _make_context_factory())
        await registry.enable("test-plugin")
        return registry

    async def test_unload_active_plugin_disables_first(self, tmp_path) -> None:
        registry = await self._setup_active_plugin(tmp_path)
        await registry.unload("test-plugin")
        assert registry.get_state("test-plugin") == PluginState.UNLOADED
        entry = registry.get("test-plugin")
        assert entry is not None
        assert entry.instance is None

    async def test_unload_loaded_plugin(self, tmp_path) -> None:
        _write_yaml_manifest(tmp_path / "test-plugin", "test-plugin")
        (tmp_path / "test-plugin" / "plugin.py").write_text(
            "from agent33.plugins.base import PluginBase\n\n"
            "class Plugin(PluginBase):\n"
            "    async def on_load(self): pass\n"
            "    async def on_unload(self): pass\n",
            encoding="utf-8",
        )
        registry = PluginRegistry()
        registry.discover(tmp_path)
        await registry.load("test-plugin", _make_context_factory())
        await registry.unload("test-plugin")
        assert registry.get_state("test-plugin") == PluginState.UNLOADED

    async def test_unload_all(self, tmp_path) -> None:
        registry = await self._setup_active_plugin(tmp_path)
        await registry.unload_all()
        assert registry.get_state("test-plugin") == PluginState.UNLOADED


class TestPluginCRUD:
    """Tests for CRUD and query methods."""

    def test_get_nonexistent_returns_none(self) -> None:
        registry = PluginRegistry()
        assert registry.get("ghost") is None

    def test_get_manifest_nonexistent_returns_none(self) -> None:
        registry = PluginRegistry()
        assert registry.get_manifest("ghost") is None

    def test_get_state_nonexistent_returns_none(self) -> None:
        registry = PluginRegistry()
        assert registry.get_state("ghost") is None

    def test_list_all_returns_sorted(self, tmp_path) -> None:
        _write_yaml_manifest(tmp_path / "charlie", "charlie")
        _write_yaml_manifest(tmp_path / "alpha", "alpha")
        _write_yaml_manifest(tmp_path / "bravo", "bravo")
        registry = PluginRegistry()
        registry.discover(tmp_path)

        names = [m.name for m in registry.list_all()]
        assert names == ["alpha", "bravo", "charlie"]

    async def test_list_active(self, tmp_path) -> None:
        _write_yaml_manifest(tmp_path / "active-plugin", "active-plugin")
        _write_yaml_manifest(tmp_path / "inactive-plugin", "inactive-plugin")
        for name in ("active-plugin", "inactive-plugin"):
            (tmp_path / name / "plugin.py").write_text(
                "from agent33.plugins.base import PluginBase\n\n"
                "class Plugin(PluginBase):\n"
                "    async def on_load(self): pass\n"
                "    async def on_enable(self): pass\n",
                encoding="utf-8",
            )
        registry = PluginRegistry()
        registry.discover(tmp_path)
        await registry.load_all(_make_context_factory())
        await registry.enable("active-plugin")

        active = registry.list_active()
        assert len(active) == 1
        assert active[0].name == "active-plugin"

    def test_count_and_active_count(self, tmp_path) -> None:
        _write_yaml_manifest(tmp_path / "a", "a-plugin")
        _write_yaml_manifest(tmp_path / "b", "b-plugin")
        registry = PluginRegistry()
        registry.discover(tmp_path)
        assert registry.count == 2
        assert registry.active_count == 0

    def test_remove_discovered_plugin(self, tmp_path) -> None:
        _write_yaml_manifest(tmp_path / "removable", "removable")
        registry = PluginRegistry()
        registry.discover(tmp_path)
        assert registry.remove("removable") is True
        assert registry.count == 0

    def test_remove_nonexistent_returns_false(self) -> None:
        registry = PluginRegistry()
        assert registry.remove("ghost") is False

    async def test_remove_active_plugin_raises(self, tmp_path) -> None:
        _write_yaml_manifest(tmp_path / "active-plugin", "active-plugin")
        (tmp_path / "active-plugin" / "plugin.py").write_text(
            "from agent33.plugins.base import PluginBase\n\n"
            "class Plugin(PluginBase):\n"
            "    async def on_load(self): pass\n"
            "    async def on_enable(self): pass\n",
            encoding="utf-8",
        )
        registry = PluginRegistry()
        registry.discover(tmp_path)
        await registry.load("active-plugin", _make_context_factory())
        await registry.enable("active-plugin")

        with pytest.raises(RuntimeError, match="Unload it first"):
            registry.remove("active-plugin")


class TestPluginSearch:
    """Tests for search and find methods."""

    def test_find_by_tag(self, tmp_path) -> None:
        _write_yaml_manifest(tmp_path / "k8s", "k8s-plugin", tags=["kubernetes"])
        _write_yaml_manifest(tmp_path / "aws", "aws-plugin", tags=["cloud"])
        registry = PluginRegistry()
        registry.discover(tmp_path)

        results = registry.find_by_tag("kubernetes")
        assert len(results) == 1
        assert results[0].name == "k8s-plugin"

    def test_find_by_tag_no_match(self, tmp_path) -> None:
        _write_yaml_manifest(tmp_path / "k8s", "k8s-plugin", tags=["kubernetes"])
        registry = PluginRegistry()
        registry.discover(tmp_path)
        assert registry.find_by_tag("nonexistent") == []

    def test_find_by_contribution(self, tmp_path) -> None:
        _write_yaml_manifest(
            tmp_path / "skill-provider",
            "skill-provider",
            contributions={"skills": ["my-skill"]},
        )
        registry = PluginRegistry()
        registry.discover(tmp_path)
        results = registry.find_by_contribution("skills", "my-skill")
        assert len(results) == 1
        assert results[0].name == "skill-provider"

    def test_search_by_name(self, tmp_path) -> None:
        _write_yaml_manifest(tmp_path / "k8s", "k8s-deploy", description="Kubernetes deploy")
        _write_yaml_manifest(tmp_path / "aws", "aws-deploy", description="AWS deploy")
        registry = PluginRegistry()
        registry.discover(tmp_path)

        results = registry.search("k8s")
        assert len(results) == 1
        assert results[0].name == "k8s-deploy"

    def test_search_by_description(self, tmp_path) -> None:
        _write_yaml_manifest(tmp_path / "k8s", "k8s-deploy", description="Kubernetes deploy")
        _write_yaml_manifest(tmp_path / "aws", "aws-deploy", description="AWS deploy")
        registry = PluginRegistry()
        registry.discover(tmp_path)

        results = registry.search("kubernetes")
        assert len(results) == 1
        assert results[0].name == "k8s-deploy"

    def test_search_by_tag(self, tmp_path) -> None:
        _write_yaml_manifest(tmp_path / "k8s", "k8s-deploy", tags=["infra"])
        _write_yaml_manifest(tmp_path / "aws", "aws-deploy", tags=["cloud"])
        registry = PluginRegistry()
        registry.discover(tmp_path)

        results = registry.search("infra")
        assert len(results) == 1

    def test_search_case_insensitive(self, tmp_path) -> None:
        _write_yaml_manifest(tmp_path / "k8s", "k8s-deploy", description="Kubernetes Deploy")
        registry = PluginRegistry()
        registry.discover(tmp_path)

        results = registry.search("KUBERNETES")
        assert len(results) == 1

    def test_search_no_results(self, tmp_path) -> None:
        _write_yaml_manifest(tmp_path / "k8s", "k8s-deploy")
        registry = PluginRegistry()
        registry.discover(tmp_path)

        results = registry.search("nonexistent")
        assert results == []
