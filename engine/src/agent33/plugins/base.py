"""PluginBase abstract class with lifecycle methods and contribution helpers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent33.plugins.context import PluginContext
    from agent33.plugins.manifest import PluginManifest

logger = logging.getLogger(__name__)


class PluginBase:
    """Base class for all AGENT-33 plugins.

    Plugins subclass this and override lifecycle methods as needed.
    All methods have no-op defaults so simple plugins need only
    implement what they use.

    Lifecycle order:
        __init__() -> on_load() -> on_enable() -> [running] -> on_disable() -> on_unload()

    The context object provides access to registries, configuration,
    and hook registration APIs. It is available after __init__().
    """

    def __init__(self, manifest: PluginManifest, context: PluginContext) -> None:
        self._manifest = manifest
        self._context = context
        self._logger = logging.getLogger(f"agent33.plugins.{manifest.name}")

    @property
    def manifest(self) -> PluginManifest:
        """The plugin's parsed manifest."""
        return self._manifest

    @property
    def context(self) -> PluginContext:
        """The plugin's execution context (registries, config, hooks)."""
        return self._context

    @property
    def name(self) -> str:
        """Shortcut for manifest.name."""
        return self._manifest.name

    @property
    def version(self) -> str:
        """Shortcut for manifest.version."""
        return self._manifest.version

    # ------------------------------------------------------------------
    # Lifecycle Methods
    # ------------------------------------------------------------------

    async def on_load(self) -> None:
        """Called after the plugin class is instantiated and dependencies are resolved.

        Use this to:
        - Register skills (via self.context.skill_registry)
        - Register tools (via self.context.tool_registry)
        - Register agent definitions (via self.context.agent_registry)
        - Perform one-time initialization (DB connections, file loading)

        This is called once during plugin loading, before on_enable().
        The plugin is not yet active -- its contributions are registered
        but not yet available to tenants.
        """

    async def on_enable(self) -> None:
        """Called when the plugin transitions from loaded to active.

        Use this to:
        - Register hooks (via self.context.hook_registry)
        - Start background tasks
        - Emit plugin_enabled events

        After this returns, the plugin's contributions are live.
        This may be called multiple times if the plugin is toggled.
        """

    async def on_disable(self) -> None:
        """Called when the plugin transitions from active to disabled.

        Use this to:
        - Deregister hooks
        - Stop background tasks
        - Clean up transient state

        After this returns, the plugin's hooks are inactive but its
        skills/tools/agents remain registered (just not discoverable).
        """

    async def on_unload(self) -> None:
        """Called when the plugin is being completely removed.

        Use this to:
        - Close connections
        - Release resources
        - Deregister skills, tools, agents

        After this returns, all plugin contributions are removed.
        This is called once, during plugin teardown.
        """

    # ------------------------------------------------------------------
    # Contribution Helpers
    # ------------------------------------------------------------------

    def register_skill(self, skill: Any) -> None:
        """Register a SkillDefinition through the context.

        Validates that the skill name is declared in the manifest's
        contributions.skills list.
        """
        from agent33.skills.definition import SkillDefinition

        if not isinstance(skill, SkillDefinition):
            raise TypeError(f"Expected SkillDefinition, got {type(skill).__name__}")

        if skill.name not in self._manifest.contributions.skills:
            raise ValueError(
                f"Plugin '{self.name}' tried to register undeclared skill "
                f"'{skill.name}'. Add it to contributions.skills in the manifest."
            )

        self._context.skill_registry.register(skill)
        self._logger.info("Registered skill: %s", skill.name)

    def register_tool(self, tool: Any) -> None:
        """Register a Tool through the context.

        Validates that the tool's class name is declared in the manifest's
        contributions.tools list.
        """
        from agent33.tools.base import Tool

        if not isinstance(tool, Tool):
            raise TypeError(f"Expected Tool, got {type(tool).__name__}")

        class_name = type(tool).__name__
        if class_name not in self._manifest.contributions.tools:
            raise ValueError(
                f"Plugin '{self.name}' tried to register undeclared tool "
                f"'{class_name}'. Add it to contributions.tools in the manifest."
            )

        self._context.tool_registry.register(tool)
        self._logger.info("Registered tool: %s", tool.name)

    def register_hook(self, hook: Any, *, priority: int = 0) -> None:
        """Register a Hook through the context.

        Requires PluginPermission.HOOK_REGISTER in the manifest.
        Validates that the hook's class name is declared in contributions.hooks.
        Requires that hook_registry is available in the context (H01 must be present).
        """
        from agent33.plugins.manifest import PluginPermission

        if PluginPermission.HOOK_REGISTER not in self._manifest.permissions:
            raise PermissionError(
                f"Plugin '{self.name}' lacks hook:register permission. "
                f"Add it to the manifest's permissions list."
            )

        class_name = type(hook).__name__
        if class_name not in self._manifest.contributions.hooks:
            raise ValueError(
                f"Plugin '{self.name}' tried to register undeclared hook "
                f"'{class_name}'. Add it to contributions.hooks in the manifest."
            )

        if self._context.hook_registry is None:
            raise RuntimeError(
                f"Plugin '{self.name}' tried to register hook '{class_name}' "
                f"but no hook_registry is available. "
                f"The Hook Framework (H01) may not be installed."
            )

        self._context.hook_registry.register(hook, priority=priority, source=self.name)
        self._logger.info("Registered hook: %s (priority=%d)", class_name, priority)
