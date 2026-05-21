"""Plugin manifest file parsing: YAML, TOML, and Markdown frontmatter formats."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agent33.plugins.manifest import PluginManifest
from agent33.skills.loader import parse_frontmatter

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


def load_manifest(plugin_dir: Path) -> PluginManifest:
    """Load a plugin manifest from a directory.

    Checks for plugin.yaml, plugin.toml, then PLUGIN.md (in order).
    Raises FileNotFoundError if no manifest is found.
    """
    # 1. Try plugin.yaml / plugin.yml
    for yaml_name in ("plugin.yaml", "plugin.yml"):
        yaml_path = plugin_dir / yaml_name
        if yaml_path.is_file():
            return _load_yaml_manifest(yaml_path)

    # 2. Try plugin.toml
    toml_path = plugin_dir / "plugin.toml"
    if toml_path.is_file():
        return _load_toml_manifest(toml_path)

    # 3. Try PLUGIN.md (frontmatter)
    md_path = plugin_dir / "PLUGIN.md"
    if md_path.is_file():
        return _load_md_manifest(md_path)

    raise FileNotFoundError(
        f"No plugin manifest found in {plugin_dir} "
        f"(expected plugin.yaml, plugin.toml, or PLUGIN.md)"
    )


def _load_yaml_manifest(path: Path) -> PluginManifest:
    """Parse a YAML plugin manifest."""
    import yaml

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Plugin YAML must be a mapping: {path}")
    return PluginManifest.model_validate(raw)


def _load_toml_manifest(path: Path) -> PluginManifest:
    """Parse a TOML plugin manifest."""
    import tomllib

    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    # TOML plugin section is under [plugin] if present
    plugin_data = raw.get("plugin", raw)
    return PluginManifest.model_validate(plugin_data)


def _load_md_manifest(path: Path) -> PluginManifest:
    """Parse a PLUGIN.md manifest with YAML frontmatter."""
    content = path.read_text(encoding="utf-8")
    metadata, body = parse_frontmatter(content)
    if body and "description" not in metadata:
        metadata["description"] = body[:500]
    return PluginManifest.model_validate(metadata)
