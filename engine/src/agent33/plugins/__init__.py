"""Plugin SDK for AGENT-33: extensible plugin framework with lifecycle management."""

from agent33.plugins.base import PluginBase
from agent33.plugins.context import PluginContext
from agent33.plugins.loader import load_manifest
from agent33.plugins.manifest import PluginManifest, PluginPermission, PluginStatus
from agent33.plugins.models import PluginScope, PluginState
from agent33.plugins.registry import PluginRegistry

__all__ = [
    "PluginBase",
    "PluginContext",
    "PluginManifest",
    "PluginPermission",
    "PluginRegistry",
    "PluginScope",
    "PluginState",
    "PluginStatus",
    "load_manifest",
]
