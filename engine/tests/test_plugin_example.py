"""Tests for the word-count example plugin.

Covers manifest correctness, lifecycle methods, execute() behaviour with
various inputs and edge cases, config validation, and integration with the
PluginRegistry and PluginLoader.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent33.plugins.capabilities import CapabilityGrant
from agent33.plugins.context import PluginContext
from agent33.plugins.examples.word_count_plugin import (
    WordCountPlugin,
    _build_manifest,
)
from agent33.plugins.loader import load_manifest
from agent33.plugins.manifest import PluginManifest, PluginPermission, PluginStatus
from agent33.plugins.models import PluginState
from agent33.plugins.registry import PluginRegistry
from agent33.plugins.scoped import ScopedSkillRegistry, ScopedToolRegistry
from agent33.skills.registry import SkillRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples" / "plugins" / "word_count"


def _make_context(
    plugin_config: dict[str, Any] | None = None,
    plugin_dir: Path | None = None,
) -> PluginContext:
    """Build a minimal PluginContext for unit tests."""
    return PluginContext(
        plugin_name="word-count",
        plugin_dir=plugin_dir or Path("/tmp/word-count"),
        granted_permissions=frozenset(["config:read"]),
        plugin_config=plugin_config or {},
    )


def _make_plugin(
    plugin_config: dict[str, Any] | None = None,
) -> WordCountPlugin:
    """Instantiate a WordCountPlugin with default manifest and context."""
    manifest = _build_manifest()
    context = _make_context(plugin_config=plugin_config)
    return WordCountPlugin(manifest, context)


def _make_context_factory() -> Any:
    """Context factory compatible with PluginRegistry.load()."""
    skill_reg = SkillRegistry()
    tool_reg = MagicMock()

    def factory(manifest: PluginManifest, plugin_dir: Path) -> PluginContext:
        grants = CapabilityGrant(
            manifest_permissions=[p.value for p in manifest.permissions],
        )
        return PluginContext(
            plugin_name=manifest.name,
            plugin_dir=plugin_dir,
            granted_permissions=grants.effective_permissions,
            skill_registry=ScopedSkillRegistry(skill_reg, grants),
            tool_registry=ScopedToolRegistry(tool_reg, grants),
            hook_registry=None,
        )

    return factory


# =========================================================================
# 1. Manifest tests
# =========================================================================


class TestWordCountManifest:
    """Verify the built-in manifest has correct metadata."""

    def test_manifest_name(self) -> None:
        m = _build_manifest()
        assert m.name == "word-count"

    def test_manifest_version(self) -> None:
        m = _build_manifest()
        assert m.version == "1.0.0"

    def test_manifest_description(self) -> None:
        m = _build_manifest()
        assert "word" in m.description.lower()
        assert "character" in m.description.lower()

    def test_manifest_author(self) -> None:
        m = _build_manifest()
        assert m.author == "AGENT-33 Contributors"

    def test_manifest_homepage(self) -> None:
        m = _build_manifest()
        assert m.homepage.startswith("https://")

    def test_manifest_permissions(self) -> None:
        m = _build_manifest()
        assert PluginPermission.CONFIG_READ in m.permissions

    def test_manifest_status_active(self) -> None:
        m = _build_manifest()
        assert m.status == PluginStatus.ACTIVE

    def test_manifest_tags(self) -> None:
        m = _build_manifest()
        assert "example" in m.tags
        assert "text-processing" in m.tags

    def test_manifest_entry_point(self) -> None:
        m = _build_manifest()
        assert m.entry_point == "word_count_plugin:WordCountPlugin"

    def test_get_manifest_via_instance(self) -> None:
        """``plugin.manifest`` returns the same data as ``_build_manifest()``."""
        plugin = _make_plugin()
        assert plugin.manifest.name == "word-count"
        assert plugin.manifest.version == "1.0.0"

    def test_static_default_manifest(self) -> None:
        """``WordCountPlugin.default_manifest()`` works without an instance."""
        m = WordCountPlugin.default_manifest()
        assert m.name == "word-count"


# =========================================================================
# 2. Lifecycle tests (on_load / on_enable / on_disable / on_unload)
# =========================================================================


class TestWordCountLifecycle:
    """Verify lifecycle methods and config validation."""

    async def test_on_load_default_config(self) -> None:
        """on_load() with no config uses the default max_text_length."""
        plugin = _make_plugin()
        await plugin.on_load()
        assert plugin.is_initialized is True
        assert plugin.max_text_length == 10_000

    async def test_on_load_custom_max_text_length(self) -> None:
        """on_load() accepts a custom max_text_length."""
        plugin = _make_plugin(plugin_config={"max_text_length": 500})
        await plugin.on_load()
        assert plugin.max_text_length == 500

    async def test_on_load_invalid_type_raises_value_error(self) -> None:
        """on_load() rejects a non-int max_text_length."""
        plugin = _make_plugin(plugin_config={"max_text_length": "not-a-number"})
        with pytest.raises(ValueError, match="must be an int"):
            await plugin.on_load()

    async def test_on_load_bool_type_raises_value_error(self) -> None:
        """on_load() rejects a boolean max_text_length (bool is a subclass of int)."""
        plugin = _make_plugin(plugin_config={"max_text_length": True})
        with pytest.raises(ValueError, match="must be an int"):
            await plugin.on_load()

    async def test_on_load_negative_raises_value_error(self) -> None:
        """on_load() rejects a non-positive max_text_length."""
        plugin = _make_plugin(plugin_config={"max_text_length": -1})
        with pytest.raises(ValueError, match="must be positive"):
            await plugin.on_load()

    async def test_on_load_zero_raises_value_error(self) -> None:
        """on_load() rejects zero as max_text_length."""
        plugin = _make_plugin(plugin_config={"max_text_length": 0})
        with pytest.raises(ValueError, match="must be positive"):
            await plugin.on_load()

    async def test_on_enable_after_load(self) -> None:
        """on_enable() runs without error after a successful on_load()."""
        plugin = _make_plugin()
        await plugin.on_load()
        await plugin.on_enable()
        # No exception is the success criteria; plugin stays initialized.
        assert plugin.is_initialized is True

    async def test_on_disable_after_enable(self) -> None:
        """on_disable() runs without error after on_enable()."""
        plugin = _make_plugin()
        await plugin.on_load()
        await plugin.on_enable()
        await plugin.on_disable()
        assert plugin.is_initialized is True

    async def test_on_unload_clears_initialized(self) -> None:
        """on_unload() resets is_initialized to False."""
        plugin = _make_plugin()
        await plugin.on_load()
        assert plugin.is_initialized is True
        await plugin.on_unload()
        assert plugin.is_initialized is False


# =========================================================================
# 3. execute() behaviour tests
# =========================================================================


class TestWordCountExecute:
    """Verify execute() with various inputs and edge cases."""

    async def test_simple_sentence(self) -> None:
        plugin = _make_plugin()
        await plugin.on_load()
        result = plugin.execute("hello world")
        assert result == {"word_count": 2, "char_count": 11, "line_count": 1}

    async def test_empty_string_returns_zeros(self) -> None:
        plugin = _make_plugin()
        await plugin.on_load()
        result = plugin.execute("")
        assert result == {"word_count": 0, "char_count": 0, "line_count": 0}

    async def test_single_word(self) -> None:
        plugin = _make_plugin()
        await plugin.on_load()
        result = plugin.execute("hello")
        assert result == {"word_count": 1, "char_count": 5, "line_count": 1}

    async def test_multiline_text(self) -> None:
        text = "line one\nline two\nline three"
        plugin = _make_plugin()
        await plugin.on_load()
        result = plugin.execute(text)
        assert result["line_count"] == 3
        assert result["word_count"] == 6

    async def test_trailing_newline(self) -> None:
        """A trailing newline adds an extra (empty) line."""
        text = "line one\nline two\n"
        plugin = _make_plugin()
        await plugin.on_load()
        result = plugin.execute(text)
        assert result["line_count"] == 3

    async def test_whitespace_only(self) -> None:
        """Whitespace-only text has 0 words but still has characters and lines."""
        plugin = _make_plugin()
        await plugin.on_load()
        result = plugin.execute("   \n   ")
        assert result["word_count"] == 0
        assert result["char_count"] == 7
        assert result["line_count"] == 2

    async def test_unicode_text(self) -> None:
        plugin = _make_plugin()
        await plugin.on_load()
        result = plugin.execute("cafe latte")
        assert result["word_count"] == 2
        assert result["char_count"] == 10

    async def test_tabs_and_mixed_whitespace(self) -> None:
        plugin = _make_plugin()
        await plugin.on_load()
        result = plugin.execute("a\tb\tc")
        assert result["word_count"] == 3

    async def test_exceeds_max_text_length_raises(self) -> None:
        plugin = _make_plugin(plugin_config={"max_text_length": 5})
        await plugin.on_load()
        with pytest.raises(ValueError, match="exceeds max_text_length"):
            plugin.execute("123456")

    async def test_exactly_at_max_text_length(self) -> None:
        """Text with length == max_text_length should succeed."""
        plugin = _make_plugin(plugin_config={"max_text_length": 5})
        await plugin.on_load()
        result = plugin.execute("12345")
        assert result["char_count"] == 5

    async def test_non_string_input_raises_type_error(self) -> None:
        plugin = _make_plugin()
        await plugin.on_load()
        with pytest.raises(TypeError, match="must be a str"):
            plugin.execute(12345)  # type: ignore[arg-type]

    async def test_large_text_within_default_limit(self) -> None:
        """A text just under the default 10k limit should work."""
        plugin = _make_plugin()
        await plugin.on_load()
        text = "word " * 1999 + "word"  # 9999 chars
        result = plugin.execute(text)
        assert result["word_count"] == 2000


# =========================================================================
# 4. YAML manifest file loading
# =========================================================================


class TestYamlManifestLoading:
    """Verify the on-disk YAML manifest can be loaded via PluginLoader."""

    def test_load_manifest_from_examples_dir(self) -> None:
        """load_manifest() parses the example YAML into a valid PluginManifest."""
        if not _EXAMPLES_DIR.is_dir():
            pytest.skip("examples/plugins/word_count directory not found")
        manifest = load_manifest(_EXAMPLES_DIR)
        assert manifest.name == "word-count"
        assert manifest.version == "1.0.0"
        assert manifest.entry_point == "word_count_plugin:WordCountPlugin"

    def test_yaml_manifest_matches_code_manifest(self) -> None:
        """The YAML file produces an identical manifest to _build_manifest()."""
        if not _EXAMPLES_DIR.is_dir():
            pytest.skip("examples/plugins/word_count directory not found")
        from_yaml = load_manifest(_EXAMPLES_DIR)
        from_code = _build_manifest()
        assert from_yaml.name == from_code.name
        assert from_yaml.version == from_code.version
        assert from_yaml.description == from_code.description
        assert from_yaml.author == from_code.author
        assert from_yaml.homepage == from_code.homepage
        assert from_yaml.entry_point == from_code.entry_point
        assert set(from_yaml.permissions) == set(from_code.permissions)
        assert from_yaml.status == from_code.status
        assert set(from_yaml.tags) == set(from_code.tags)


# =========================================================================
# 5. Registry integration
# =========================================================================


class TestRegistryIntegration:
    """Tests that exercise the plugin through the PluginRegistry."""

    def _write_word_count_plugin(self, base_dir: Path) -> Path:
        """Copy the word-count plugin files into a temp directory."""
        plugin_dir = base_dir / "word-count"
        plugin_dir.mkdir(parents=True, exist_ok=True)

        # Write manifest
        (plugin_dir / "plugin.yaml").write_text(
            "name: word-count\n"
            'version: "1.0.0"\n'
            'description: "Count words, characters, and lines in a text string."\n'
            'author: "AGENT-33 Contributors"\n'
            'homepage: "https://github.com/mattmre/AGENT33"\n'
            'entry_point: "word_count_plugin:WordCountPlugin"\n'
            "permissions:\n"
            "  - config:read\n"
            "tags:\n"
            "  - example\n"
            "  - text-processing\n"
            "  - utility\n"
            "status: active\n",
            encoding="utf-8",
        )

        # Copy the actual plugin module so the loader can import it
        src_module = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "agent33"
            / "plugins"
            / "examples"
            / "word_count_plugin.py"
        )
        shutil.copy2(str(src_module), str(plugin_dir / "word_count_plugin.py"))
        return plugin_dir

    async def test_discover_registers_plugin(self, tmp_path: Path) -> None:
        self._write_word_count_plugin(tmp_path)
        registry = PluginRegistry()
        count = registry.discover(tmp_path)
        assert count == 1
        assert registry.get("word-count") is not None

    async def test_list_all_includes_word_count(self, tmp_path: Path) -> None:
        self._write_word_count_plugin(tmp_path)
        registry = PluginRegistry()
        registry.discover(tmp_path)
        manifests = registry.list_all()
        names = [m.name for m in manifests]
        assert "word-count" in names

    async def test_load_produces_working_instance(self, tmp_path: Path) -> None:
        self._write_word_count_plugin(tmp_path)
        registry = PluginRegistry()
        registry.discover(tmp_path)
        await registry.load("word-count", _make_context_factory())
        entry = registry.get("word-count")
        assert entry is not None
        assert entry.state == PluginState.LOADED
        assert entry.instance is not None
        # The registry loads the module via spec_from_file_location with a
        # unique module name, so isinstance() against the test-imported class
        # fails.  Check class name and duck-type instead.
        assert type(entry.instance).__name__ == "WordCountPlugin"
        assert hasattr(entry.instance, "execute")

    async def test_full_lifecycle_via_registry(self, tmp_path: Path) -> None:
        """discover -> load -> enable -> execute -> disable -> unload -> remove."""
        self._write_word_count_plugin(tmp_path)
        registry = PluginRegistry()

        # Discover
        registry.discover(tmp_path)
        assert registry.get_state("word-count") == PluginState.DISCOVERED

        # Load
        await registry.load("word-count", _make_context_factory())
        assert registry.get_state("word-count") == PluginState.LOADED

        # Enable
        await registry.enable("word-count")
        assert registry.get_state("word-count") == PluginState.ACTIVE
        assert registry.active_count == 1

        # Execute (use duck-type call; see test_load_produces_working_instance
        # for why isinstance() against the test-imported class doesn't work).
        entry = registry.get("word-count")
        assert entry is not None
        assert entry.instance is not None
        instance = entry.instance
        assert type(instance).__name__ == "WordCountPlugin"
        result = instance.execute("hello world")
        assert result == {"word_count": 2, "char_count": 11, "line_count": 1}

        # Disable
        await registry.disable("word-count")
        assert registry.get_state("word-count") == PluginState.DISABLED

        # Unload
        await registry.unload("word-count")
        assert registry.get_state("word-count") == PluginState.UNLOADED

        # Remove
        removed = registry.remove("word-count")
        assert removed is True
        assert registry.get("word-count") is None
        assert registry.count == 0

    async def test_allowlist_blocks_plugin(self, tmp_path: Path) -> None:
        """A registry with an allowlist that excludes word-count rejects it.

        ``discover()`` catches and logs the PermissionError internally, so we
        call ``discover_plugin()`` directly to get the exception.
        """
        plugin_dir = self._write_word_count_plugin(tmp_path)
        registry = PluginRegistry(allowlist=["other-plugin"])
        with pytest.raises(PermissionError, match="not on the plugin allowlist"):
            registry.discover_plugin(plugin_dir)

    async def test_allowlist_permits_plugin(self, tmp_path: Path) -> None:
        """A registry with an allowlist that includes word-count allows it."""
        self._write_word_count_plugin(tmp_path)
        registry = PluginRegistry(allowlist=["word-count"])
        count = registry.discover(tmp_path)
        assert count == 1

    async def test_search_finds_word_count(self, tmp_path: Path) -> None:
        """Registry.search() finds the word-count plugin by keyword."""
        self._write_word_count_plugin(tmp_path)
        registry = PluginRegistry()
        registry.discover(tmp_path)
        results = registry.search("word")
        assert any(m.name == "word-count" for m in results)

    async def test_find_by_tag(self, tmp_path: Path) -> None:
        self._write_word_count_plugin(tmp_path)
        registry = PluginRegistry()
        registry.discover(tmp_path)
        results = registry.find_by_tag("example")
        assert any(m.name == "word-count" for m in results)
