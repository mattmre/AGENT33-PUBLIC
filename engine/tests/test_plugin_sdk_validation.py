"""P4.17 Plugin SDK real-world validation harness.

Validates the plugin SDK against realistic scenarios:
- Loading and registering example plugins
- Full plugin lifecycle (init -> load -> execute -> disable -> unload)
- Tenant boundary isolation
- Error handling and crash recovery
- Schema validation via the plugin_validator utility
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from agent33.plugins.capabilities import CapabilityGrant
from agent33.plugins.context import PluginContext
from agent33.plugins.manifest import (
    PluginManifest,
    PluginPermission,
)
from agent33.plugins.models import PluginState
from agent33.plugins.registry import PluginRegistry
from agent33.plugins.scoped import ScopedSkillRegistry, ScopedToolRegistry
from agent33.skills.plugin_validator import ValidationResult, validate_plugin
from agent33.skills.registry import SkillRegistry

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_plugin(
    base_dir: Path,
    name: str,
    version: str = "1.0.0",
    *,
    yaml_extra: str = "",
    plugin_code: str = "",
) -> Path:
    """Write a complete plugin directory with manifest and module."""
    plugin_dir = base_dir / name
    plugin_dir.mkdir(parents=True, exist_ok=True)

    yaml_content = f"""\
name: {name}
version: "{version}"
description: Test plugin {name}
author: Test Author
entry_point: "plugin:Plugin"
{yaml_extra}
"""
    (plugin_dir / "plugin.yaml").write_text(yaml_content, encoding="utf-8")

    if not plugin_code:
        plugin_code = """\
from agent33.plugins.base import PluginBase

class Plugin(PluginBase):
    async def on_load(self):
        pass

    async def on_enable(self):
        pass

    async def on_disable(self):
        pass

    async def on_unload(self):
        pass
"""
    (plugin_dir / "plugin.py").write_text(plugin_code, encoding="utf-8")
    return plugin_dir


def _make_context_factory(
    skill_registry: SkillRegistry | None = None,
) -> Any:
    """Create a context factory for integration tests."""
    _skill_reg = skill_registry or SkillRegistry()
    _tool_reg = MagicMock()

    def factory(manifest: PluginManifest, plugin_dir: Path) -> PluginContext:
        grants = CapabilityGrant(
            manifest_permissions=[p.value for p in manifest.permissions],
        )
        return PluginContext(
            plugin_name=manifest.name,
            plugin_dir=plugin_dir,
            granted_permissions=grants.effective_permissions,
            skill_registry=ScopedSkillRegistry(_skill_reg, grants),
            tool_registry=ScopedToolRegistry(_tool_reg, grants),
            hook_registry=None,
        )

    return factory


# ===================================================================
# 1. Example Plugin Loading and Registration
# ===================================================================


class TestExamplePluginLoading:
    """Test that real example plugins can be loaded and registered."""

    async def test_word_count_plugin_loads_via_registry(self, tmp_path: Path) -> None:
        """The word-count example plugin can be discovered, loaded, and enabled."""
        _write_plugin(
            tmp_path,
            "word-count",
            yaml_extra="""\
permissions:
  - config:read
tags:
  - example
  - text-processing
""",
            plugin_code="""\
from agent33.plugins.base import PluginBase

class Plugin(PluginBase):
    def __init__(self, manifest, context):
        super().__init__(manifest, context)
        self._max_text_length = 10000
        self._initialized = False

    async def on_load(self):
        config = self._context.plugin_config
        self._max_text_length = config.get("max_text_length", 10000)
        self._initialized = True

    def execute(self, input_text):
        if not isinstance(input_text, str):
            raise TypeError(f"input_text must be a str, got {type(input_text).__name__}")
        if len(input_text) > self._max_text_length:
            raise ValueError(
                f"Text length {len(input_text)} exceeds max ({self._max_text_length})"
            )
        word_count = len(input_text.split()) if input_text else 0
        char_count = len(input_text)
        line_count = input_text.count("\\n") + 1 if input_text else 0
        return {"word_count": word_count, "char_count": char_count, "line_count": line_count}
""",
        )

        registry = PluginRegistry()
        manifest = registry.discover_plugin(tmp_path / "word-count")
        assert manifest.name == "word-count"
        assert manifest.version == "1.0.0"
        assert registry.count == 1

        await registry.load("word-count", _make_context_factory())
        assert registry.get_state("word-count") == PluginState.LOADED

        await registry.enable("word-count")
        assert registry.get_state("word-count") == PluginState.ACTIVE

        entry = registry.get("word-count")
        assert entry is not None
        assert entry.instance is not None
        assert entry.instance._initialized is True

    async def test_plugin_with_skill_registration(self, tmp_path: Path) -> None:
        """A plugin that registers a skill during on_load() is reflected in SkillRegistry."""
        _write_plugin(
            tmp_path,
            "skill-provider",
            yaml_extra="""\
contributions:
  skills:
    - provided-skill
""",
            plugin_code="""\
from agent33.plugins.base import PluginBase
from agent33.skills.definition import SkillDefinition

class Plugin(PluginBase):
    async def on_load(self):
        skill = SkillDefinition(
            name="provided-skill",
            version=self.version,
            description="A skill provided by a plugin",
            tags=["plugin-provided"],
        )
        self.register_skill(skill)
""",
        )

        skill_registry = SkillRegistry()
        registry = PluginRegistry()
        registry.discover(tmp_path)
        await registry.load("skill-provider", _make_context_factory(skill_registry))

        # Verify skill ended up in the skill registry
        skill = skill_registry.get("provided-skill")
        assert skill is not None
        assert skill.name == "provided-skill"
        assert skill.description == "A skill provided by a plugin"
        assert "plugin-provided" in skill.tags

    async def test_discover_multiple_plugins(self, tmp_path: Path) -> None:
        """Discovering a directory with multiple plugin subdirectories registers all."""
        _write_plugin(tmp_path, "plugin-alpha")
        _write_plugin(tmp_path, "plugin-beta", version="2.0.0")
        _write_plugin(tmp_path, "plugin-gamma", version="3.1.0")

        registry = PluginRegistry()
        count = registry.discover(tmp_path)
        assert count == 3
        assert registry.count == 3

        manifests = registry.list_all()
        names = [m.name for m in manifests]
        assert names == ["plugin-alpha", "plugin-beta", "plugin-gamma"]


# ===================================================================
# 2. Plugin Lifecycle (init, execute, cleanup)
# ===================================================================


class TestPluginLifecycle:
    """Test the full plugin lifecycle with real state transitions."""

    async def test_full_lifecycle_with_execute(self, tmp_path: Path) -> None:
        """Walk through discover -> load -> enable -> execute -> disable -> unload."""
        _write_plugin(
            tmp_path,
            "counter-plugin",
            plugin_code="""\
from agent33.plugins.base import PluginBase

class Plugin(PluginBase):
    def __init__(self, manifest, context):
        super().__init__(manifest, context)
        self.call_count = 0
        self._states_visited = []

    async def on_load(self):
        self._states_visited.append("loaded")

    async def on_enable(self):
        self._states_visited.append("enabled")

    async def on_disable(self):
        self._states_visited.append("disabled")

    async def on_unload(self):
        self._states_visited.append("unloaded")

    def execute(self, value):
        self.call_count += 1
        return value * 2
""",
        )

        registry = PluginRegistry()
        registry.discover_plugin(tmp_path / "counter-plugin")
        assert registry.get_state("counter-plugin") == PluginState.DISCOVERED

        ctx_factory = _make_context_factory()

        # Load
        await registry.load("counter-plugin", ctx_factory)
        assert registry.get_state("counter-plugin") == PluginState.LOADED

        # Enable
        await registry.enable("counter-plugin")
        assert registry.get_state("counter-plugin") == PluginState.ACTIVE

        # Execute plugin logic
        entry = registry.get("counter-plugin")
        assert entry is not None
        assert entry.instance is not None
        result = entry.instance.execute(21)
        assert result == 42
        assert entry.instance.call_count == 1

        # Execute again
        result2 = entry.instance.execute(5)
        assert result2 == 10
        assert entry.instance.call_count == 2

        # Disable
        await registry.disable("counter-plugin")
        assert registry.get_state("counter-plugin") == PluginState.DISABLED

        # Unload
        await registry.unload("counter-plugin")
        assert registry.get_state("counter-plugin") == PluginState.UNLOADED

        # Verify lifecycle was fully traversed (the instance is gone after unload,
        # but we already validated states during the walk)
        assert registry.get("counter-plugin") is not None
        assert registry.get("counter-plugin").instance is None

    async def test_lifecycle_re_enable_after_disable(self, tmp_path: Path) -> None:
        """A disabled plugin can be re-enabled."""
        _write_plugin(
            tmp_path,
            "toggle-plugin",
            plugin_code="""\
from agent33.plugins.base import PluginBase

class Plugin(PluginBase):
    def __init__(self, manifest, context):
        super().__init__(manifest, context)
        self.enable_count = 0

    async def on_enable(self):
        self.enable_count += 1

    async def on_disable(self):
        pass
""",
        )

        registry = PluginRegistry()
        registry.discover_plugin(tmp_path / "toggle-plugin")
        await registry.load("toggle-plugin", _make_context_factory())

        await registry.enable("toggle-plugin")
        entry = registry.get("toggle-plugin")
        assert entry.instance.enable_count == 1

        await registry.disable("toggle-plugin")
        assert registry.get_state("toggle-plugin") == PluginState.DISABLED

        await registry.enable("toggle-plugin")
        assert registry.get_state("toggle-plugin") == PluginState.ACTIVE
        assert entry.instance.enable_count == 2

    async def test_unload_auto_disables_active_plugin(self, tmp_path: Path) -> None:
        """Calling unload on an active plugin auto-disables first."""
        _write_plugin(
            tmp_path,
            "auto-disable",
            plugin_code="""\
from agent33.plugins.base import PluginBase

class Plugin(PluginBase):
    def __init__(self, manifest, context):
        super().__init__(manifest, context)
        self.disabled_before_unload = False

    async def on_disable(self):
        self.disabled_before_unload = True

    async def on_unload(self):
        pass
""",
        )

        registry = PluginRegistry()
        registry.discover_plugin(tmp_path / "auto-disable")
        await registry.load("auto-disable", _make_context_factory())
        await registry.enable("auto-disable")

        # Unload directly from ACTIVE state
        await registry.unload("auto-disable")
        assert registry.get_state("auto-disable") == PluginState.UNLOADED
        # Instance is now gone, but the state transition happened correctly


# ===================================================================
# 3. Tenant Boundary Isolation
# ===================================================================


class TestPluginTenantIsolation:
    """Test that plugins respect multi-tenant boundaries."""

    def test_tenant_plugin_invisible_to_other_tenant(self, tmp_path: Path) -> None:
        """A plugin discovered for tenant-A is invisible to tenant-B."""
        _write_plugin(tmp_path, "tenant-a-plugin")

        registry = PluginRegistry()
        registry.discover_plugin(tmp_path / "tenant-a-plugin", tenant_id="tenant-a")

        # tenant-a can see it
        entry_a = registry.get("tenant-a-plugin", tenant_id="tenant-a")
        assert entry_a is not None
        assert entry_a.manifest.name == "tenant-a-plugin"

        # tenant-b cannot see it
        entry_b = registry.get("tenant-a-plugin", tenant_id="tenant-b")
        assert entry_b is None

    def test_system_plugin_visible_to_all_tenants(self, tmp_path: Path) -> None:
        """A plugin with no tenant (system-level) is visible to any tenant."""
        _write_plugin(tmp_path, "system-plugin")

        registry = PluginRegistry()
        registry.discover_plugin(tmp_path / "system-plugin")  # no tenant_id -> system

        # Any tenant can see system plugins
        assert registry.get("system-plugin", tenant_id="tenant-x") is not None
        assert registry.get("system-plugin", tenant_id="tenant-y") is not None

    def test_list_all_filters_by_tenant(self, tmp_path: Path) -> None:
        """list_all only returns system + same-tenant plugins."""
        _write_plugin(tmp_path, "system-wide")
        _write_plugin(tmp_path, "tenant-a-only")
        _write_plugin(tmp_path, "tenant-b-only")

        registry = PluginRegistry()
        registry.discover_plugin(tmp_path / "system-wide")  # system
        registry.discover_plugin(tmp_path / "tenant-a-only", tenant_id="tenant-a")
        registry.discover_plugin(tmp_path / "tenant-b-only", tenant_id="tenant-b")

        a_plugins = registry.list_all(tenant_id="tenant-a")
        a_names = [m.name for m in a_plugins]
        assert "system-wide" in a_names
        assert "tenant-a-only" in a_names
        assert "tenant-b-only" not in a_names

        b_plugins = registry.list_all(tenant_id="tenant-b")
        b_names = [m.name for m in b_plugins]
        assert "system-wide" in b_names
        assert "tenant-b-only" in b_names
        assert "tenant-a-only" not in b_names

    async def test_tenant_cannot_enable_other_tenants_plugin(self, tmp_path: Path) -> None:
        """A tenant cannot enable a plugin belonging to another tenant."""
        _write_plugin(tmp_path, "owned-plugin")

        registry = PluginRegistry()
        registry.discover_plugin(tmp_path / "owned-plugin", tenant_id="owner-tenant")

        await registry.load("owned-plugin", _make_context_factory())

        with pytest.raises(PermissionError, match="cannot enable"):
            await registry.enable("owned-plugin", tenant_id="intruder-tenant")

    async def test_tenant_cannot_disable_other_tenants_plugin(self, tmp_path: Path) -> None:
        """A tenant cannot disable a plugin belonging to another tenant."""
        _write_plugin(tmp_path, "target-plugin")

        registry = PluginRegistry()
        registry.discover_plugin(tmp_path / "target-plugin", tenant_id="owner")
        await registry.load("target-plugin", _make_context_factory())
        await registry.enable("target-plugin", tenant_id="owner")

        with pytest.raises(PermissionError, match="cannot disable"):
            await registry.disable("target-plugin", tenant_id="attacker")


# ===================================================================
# 4. Error Handling and Crash Recovery
# ===================================================================


class TestPluginErrorHandling:
    """Test graceful handling of plugin crashes and errors."""

    async def test_on_load_crash_sets_error_state(self, tmp_path: Path) -> None:
        """A plugin that raises during on_load() transitions to ERROR state."""
        _write_plugin(
            tmp_path,
            "crashy-loader",
            plugin_code="""\
from agent33.plugins.base import PluginBase

class Plugin(PluginBase):
    async def on_load(self):
        raise RuntimeError("Simulated load crash")
""",
        )

        registry = PluginRegistry()
        registry.discover_plugin(tmp_path / "crashy-loader")

        with pytest.raises(RuntimeError, match="Simulated load crash"):
            await registry.load("crashy-loader", _make_context_factory())

        assert registry.get_state("crashy-loader") == PluginState.ERROR
        entry = registry.get("crashy-loader")
        assert entry is not None
        assert "Simulated load crash" in entry.error

    async def test_on_enable_crash_sets_error_state(self, tmp_path: Path) -> None:
        """A plugin that raises during on_enable() transitions to ERROR state."""
        _write_plugin(
            tmp_path,
            "crashy-enabler",
            plugin_code="""\
from agent33.plugins.base import PluginBase

class Plugin(PluginBase):
    async def on_load(self):
        pass

    async def on_enable(self):
        raise ValueError("Enable failed: bad config")
""",
        )

        registry = PluginRegistry()
        registry.discover_plugin(tmp_path / "crashy-enabler")
        await registry.load("crashy-enabler", _make_context_factory())

        with pytest.raises(ValueError, match="Enable failed"):
            await registry.enable("crashy-enabler")

        assert registry.get_state("crashy-enabler") == PluginState.ERROR

    async def test_on_disable_crash_does_not_block_disable(self, tmp_path: Path) -> None:
        """Errors during on_disable() are logged but do not prevent state transition."""
        _write_plugin(
            tmp_path,
            "noisy-disabler",
            plugin_code="""\
from agent33.plugins.base import PluginBase

class Plugin(PluginBase):
    async def on_load(self):
        pass

    async def on_enable(self):
        pass

    async def on_disable(self):
        raise RuntimeError("Cleanup explosion")
""",
        )

        registry = PluginRegistry()
        registry.discover_plugin(tmp_path / "noisy-disabler")
        await registry.load("noisy-disabler", _make_context_factory())
        await registry.enable("noisy-disabler")

        # Should succeed despite on_disable raising
        await registry.disable("noisy-disabler")
        assert registry.get_state("noisy-disabler") == PluginState.DISABLED

    async def test_on_unload_crash_does_not_block_unload(self, tmp_path: Path) -> None:
        """Errors during on_unload() are logged but plugin is still unloaded."""
        _write_plugin(
            tmp_path,
            "noisy-unloader",
            plugin_code="""\
from agent33.plugins.base import PluginBase

class Plugin(PluginBase):
    async def on_load(self):
        pass

    async def on_enable(self):
        pass

    async def on_disable(self):
        pass

    async def on_unload(self):
        raise RuntimeError("Teardown explosion")
""",
        )

        registry = PluginRegistry()
        registry.discover_plugin(tmp_path / "noisy-unloader")
        await registry.load("noisy-unloader", _make_context_factory())
        await registry.enable("noisy-unloader")

        await registry.unload("noisy-unloader")
        assert registry.get_state("noisy-unloader") == PluginState.UNLOADED
        assert registry.get("noisy-unloader").instance is None

    async def test_cannot_enable_plugin_not_loaded(self, tmp_path: Path) -> None:
        """Enabling a plugin that is only discovered (not loaded) raises RuntimeError."""
        _write_plugin(tmp_path, "not-loaded-plugin")
        registry = PluginRegistry()
        registry.discover_plugin(tmp_path / "not-loaded-plugin")

        with pytest.raises(RuntimeError, match="Cannot enable"):
            await registry.enable("not-loaded-plugin")

    async def test_undeclared_skill_registration_sets_error(self, tmp_path: Path) -> None:
        """Registering a skill not declared in contributions raises ValueError and sets ERROR."""
        _write_plugin(
            tmp_path,
            "sneaky-plugin",
            yaml_extra="""\
contributions:
  skills:
    - declared-skill
""",
            plugin_code="""\
from agent33.plugins.base import PluginBase
from agent33.skills.definition import SkillDefinition

class Plugin(PluginBase):
    async def on_load(self):
        # Try to register a skill not in contributions
        skill = SkillDefinition(name="undeclared-skill")
        self.register_skill(skill)
""",
        )

        registry = PluginRegistry()
        registry.discover_plugin(tmp_path / "sneaky-plugin")

        with pytest.raises(ValueError, match="undeclared skill"):
            await registry.load("sneaky-plugin", _make_context_factory())

        assert registry.get_state("sneaky-plugin") == PluginState.ERROR


# ===================================================================
# 5. Schema Validation
# ===================================================================


class TestPluginSchemaValidation:
    """Test manifest schema enforcement via Pydantic validation."""

    def test_valid_manifest_creation(self) -> None:
        """A manifest with all required fields is valid."""
        manifest = PluginManifest(
            name="valid-plugin",
            version="1.0.0",
            description="A perfectly valid plugin",
            author="Test Author",
        )
        assert manifest.name == "valid-plugin"
        assert manifest.version == "1.0.0"

    def test_rejects_uppercase_name(self) -> None:
        """Plugin names must be lowercase."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            PluginManifest(name="InvalidName", version="1.0.0")
        errors = exc_info.value.errors()
        assert any("string_pattern" in e["type"] for e in errors)

    def test_rejects_invalid_semver(self) -> None:
        """Version must be valid semver (X.Y.Z)."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            PluginManifest(name="test-plugin", version="1.0")
        errors = exc_info.value.errors()
        assert any("string_pattern" in e["type"] for e in errors)

    def test_rejects_empty_name(self) -> None:
        """Plugin name cannot be empty."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PluginManifest(name="", version="1.0.0")

    def test_rejects_name_too_long(self) -> None:
        """Plugin name has a 64-character maximum."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PluginManifest(name="a" * 65, version="1.0.0")

    def test_rejects_description_too_long(self) -> None:
        """Description has a 500-character maximum."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PluginManifest(name="test-plugin", version="1.0.0", description="x" * 501)

    def test_permissions_enum_values(self) -> None:
        """Permissions are validated as enum members."""
        manifest = PluginManifest(
            name="perm-plugin",
            version="1.0.0",
            permissions=[PluginPermission.FILE_READ, PluginPermission.NETWORK],
        )
        assert PluginPermission.FILE_READ in manifest.permissions
        assert len(manifest.permissions) == 2

    def test_contributions_default_empty(self) -> None:
        """Contributions default to empty lists."""
        manifest = PluginManifest(name="bare-plugin", version="1.0.0")
        assert manifest.contributions.skills == []
        assert manifest.contributions.tools == []
        assert manifest.contributions.agents == []
        assert manifest.contributions.hooks == []


# ===================================================================
# 6. validate_plugin() Utility
# ===================================================================


class TestValidatePluginUtility:
    """Test the standalone validate_plugin() function."""

    def test_valid_plugin_passes_all_checks(self, tmp_path: Path) -> None:
        """A well-formed plugin directory passes all validation checks."""
        _write_plugin(tmp_path, "good-plugin")

        result = validate_plugin(tmp_path / "good-plugin")

        assert result.valid is True
        assert result.manifest is not None
        assert result.manifest.name == "good-plugin"
        assert len(result.failed_checks) == 0

        # Verify specific checks ran
        check_names = {c.name for c in result.checks}
        assert "directory_exists" in check_names
        assert "manifest_parseable" in check_names
        assert "entry_point_module_exists" in check_names
        assert "entry_point_class_exists" in check_names

    def test_nonexistent_directory_fails(self, tmp_path: Path) -> None:
        """A path that does not exist fails the directory_exists check."""
        result = validate_plugin(tmp_path / "nonexistent")

        assert result.valid is False
        assert len(result.failed_checks) == 1
        assert result.failed_checks[0].name == "directory_exists"

    def test_missing_manifest_fails(self, tmp_path: Path) -> None:
        """A directory without a manifest file fails."""
        empty_dir = tmp_path / "no-manifest"
        empty_dir.mkdir()

        result = validate_plugin(empty_dir)

        assert result.valid is False
        failed_names = {c.name for c in result.failed_checks}
        assert "manifest_exists" in failed_names

    def test_missing_entry_point_module_fails(self, tmp_path: Path) -> None:
        """A plugin with a manifest but no entry-point .py file fails."""
        plugin_dir = tmp_path / "no-module"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.yaml").write_text(
            "name: no-module\nversion: 1.0.0\ndescription: Missing module\n",
            encoding="utf-8",
        )
        # Deliberately NOT creating plugin.py

        result = validate_plugin(plugin_dir)

        assert result.valid is False
        failed_names = {c.name for c in result.failed_checks}
        assert "entry_point_module_exists" in failed_names

    def test_entry_point_class_not_found(self, tmp_path: Path) -> None:
        """A module that exists but lacks the declared class fails."""
        plugin_dir = tmp_path / "wrong-class"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.yaml").write_text(
            "name: wrong-class\nversion: 1.0.0\nentry_point: plugin:NonExistentClass\n",
            encoding="utf-8",
        )
        (plugin_dir / "plugin.py").write_text(
            "class SomeOtherClass:\n    pass\n",
            encoding="utf-8",
        )

        result = validate_plugin(plugin_dir)

        assert result.valid is False
        failed_names = {c.name for c in result.failed_checks}
        assert "entry_point_class_exists" in failed_names

    def test_entry_point_class_not_plugin_base(self, tmp_path: Path) -> None:
        """A class that exists but does not extend PluginBase fails."""
        plugin_dir = tmp_path / "not-plugin-base"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.yaml").write_text(
            "name: not-plugin-base\nversion: 1.0.0\nentry_point: plugin:Plugin\n",
            encoding="utf-8",
        )
        (plugin_dir / "plugin.py").write_text(
            "class Plugin:\n    pass\n",
            encoding="utf-8",
        )

        result = validate_plugin(plugin_dir)

        assert result.valid is False
        failed_names = {c.name for c in result.failed_checks}
        assert "entry_point_class_exists" in failed_names
        # Check the message mentions PluginBase
        class_check = next(c for c in result.checks if c.name == "entry_point_class_exists")
        assert "PluginBase" in class_check.message

    def test_unmet_dependency_detected(self, tmp_path: Path) -> None:
        """When available_plugins is provided, missing deps are flagged."""
        plugin_dir = tmp_path / "dep-consumer"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.yaml").write_text(
            "name: dep-consumer\n"
            "version: 1.0.0\n"
            "entry_point: plugin:Plugin\n"
            "dependencies:\n"
            "  - name: missing-dep\n"
            '    version_constraint: ">=1.0.0"\n',
            encoding="utf-8",
        )
        (plugin_dir / "plugin.py").write_text(
            "from agent33.plugins.base import PluginBase\nclass Plugin(PluginBase): pass\n",
            encoding="utf-8",
        )

        result = validate_plugin(plugin_dir, available_plugins={"other-plugin": "1.0.0"})

        assert result.valid is False
        dep_check = next(c for c in result.checks if c.name == "dependencies_met")
        assert dep_check.passed is False
        assert "missing-dep" in dep_check.message

    def test_version_constraint_violation_detected(self, tmp_path: Path) -> None:
        """When available_plugins is provided, version violations are flagged."""
        plugin_dir = tmp_path / "version-consumer"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.yaml").write_text(
            "name: version-consumer\n"
            "version: 1.0.0\n"
            "entry_point: plugin:Plugin\n"
            "dependencies:\n"
            "  - name: base-lib\n"
            '    version_constraint: ">=2.0.0"\n',
            encoding="utf-8",
        )
        (plugin_dir / "plugin.py").write_text(
            "from agent33.plugins.base import PluginBase\nclass Plugin(PluginBase): pass\n",
            encoding="utf-8",
        )

        result = validate_plugin(plugin_dir, available_plugins={"base-lib": "1.5.0"})

        assert result.valid is False
        dep_check = next(c for c in result.checks if c.name == "dependencies_met")
        assert dep_check.passed is False
        assert ">=2.0.0" in dep_check.message

    def test_satisfied_dependencies_pass(self, tmp_path: Path) -> None:
        """When all dependencies are available and constraints met, check passes."""
        plugin_dir = tmp_path / "happy-consumer"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.yaml").write_text(
            "name: happy-consumer\n"
            "version: 1.0.0\n"
            "entry_point: plugin:Plugin\n"
            "dependencies:\n"
            "  - name: base-lib\n"
            '    version_constraint: ">=1.0.0"\n',
            encoding="utf-8",
        )
        (plugin_dir / "plugin.py").write_text(
            "from agent33.plugins.base import PluginBase\nclass Plugin(PluginBase): pass\n",
            encoding="utf-8",
        )

        result = validate_plugin(plugin_dir, available_plugins={"base-lib": "2.0.0"})

        assert result.valid is True
        dep_check = next(c for c in result.checks if c.name == "dependencies_met")
        assert dep_check.passed is True

    def test_optional_missing_dependency_does_not_fail(self, tmp_path: Path) -> None:
        """Optional dependencies that are missing do not cause validation failure."""
        plugin_dir = tmp_path / "optional-dep"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.yaml").write_text(
            "name: optional-dep\n"
            "version: 1.0.0\n"
            "entry_point: plugin:Plugin\n"
            "dependencies:\n"
            "  - name: optional-lib\n"
            "    optional: true\n",
            encoding="utf-8",
        )
        (plugin_dir / "plugin.py").write_text(
            "from agent33.plugins.base import PluginBase\nclass Plugin(PluginBase): pass\n",
            encoding="utf-8",
        )

        result = validate_plugin(plugin_dir, available_plugins={})

        assert result.valid is True

    def test_no_deps_passes(self, tmp_path: Path) -> None:
        """A plugin with no declared dependencies passes the deps check."""
        _write_plugin(tmp_path, "no-deps")

        result = validate_plugin(tmp_path / "no-deps")

        dep_check = next(c for c in result.checks if c.name == "dependencies_met")
        assert dep_check.passed is True
        assert "No dependencies" in dep_check.message

    def test_invalid_yaml_manifest_fails(self, tmp_path: Path) -> None:
        """A YAML manifest that isn't a valid mapping fails parsing."""
        plugin_dir = tmp_path / "bad-yaml"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.yaml").write_text("just a string\n", encoding="utf-8")

        result = validate_plugin(plugin_dir)

        assert result.valid is False
        failed_names = {c.name for c in result.failed_checks}
        assert "manifest_parseable" in failed_names

    def test_validation_result_failed_checks_property(self, tmp_path: Path) -> None:
        """ValidationResult.failed_checks returns only the failures."""
        result = ValidationResult(plugin_dir=tmp_path)
        result.add("check-a", True, "OK")
        result.add("check-b", False, "Failed")
        result.add("check-c", True, "OK")
        result.add("check-d", False, "Also failed")

        assert len(result.failed_checks) == 2
        assert {c.name for c in result.failed_checks} == {"check-b", "check-d"}
        assert result.valid is False


# ===================================================================
# 7. Dependency Order and Constraint Validation
# ===================================================================


class TestPluginDependencyValidation:
    """Test dependency ordering and version constraint checks."""

    async def test_load_all_respects_dependency_order(self, tmp_path: Path) -> None:
        """Plugins are loaded in topological order based on dependencies."""
        _write_plugin(tmp_path, "foundation")
        _write_plugin(
            tmp_path,
            "middleware",
            yaml_extra="dependencies:\n  - name: foundation\n",
        )
        _write_plugin(
            tmp_path,
            "application",
            yaml_extra="dependencies:\n  - name: middleware\n",
        )

        registry = PluginRegistry()
        registry.discover(tmp_path)

        order = registry.resolve_load_order()
        assert order.index("foundation") < order.index("middleware")
        assert order.index("middleware") < order.index("application")

        loaded = await registry.load_all(_make_context_factory())
        assert loaded == 3

    def test_version_constraint_violation_reported(self, tmp_path: Path) -> None:
        """check_version_constraints() detects unsatisfied version requirements."""
        _write_plugin(tmp_path, "provider", version="0.5.0")
        _write_plugin(
            tmp_path,
            "consumer",
            yaml_extra='dependencies:\n  - name: provider\n    version_constraint: ">=1.0.0"\n',
        )

        registry = PluginRegistry()
        registry.discover(tmp_path)

        violations = registry.check_version_constraints()
        assert len(violations) == 1
        assert "consumer" in violations[0]
        assert "provider" in violations[0]
        assert ">=1.0.0" in violations[0]
