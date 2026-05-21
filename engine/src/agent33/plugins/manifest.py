"""Plugin manifest model: declarative metadata loaded before plugin code executes."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class PluginStatus(StrEnum):
    """Lifecycle status of a plugin."""

    ACTIVE = "active"
    DEPRECATED = "deprecated"
    EXPERIMENTAL = "experimental"


class PluginCapabilityType(StrEnum):
    """What a plugin can contribute to the system."""

    SKILLS = "skills"
    TOOLS = "tools"
    AGENTS = "agents"
    HOOKS = "hooks"
    CONFIGURATION = "config"


class PluginPermission(StrEnum):
    """System capabilities a plugin can request."""

    FILE_READ = "file:read"
    FILE_WRITE = "file:write"
    NETWORK = "network"
    DATABASE_READ = "database:read"
    DATABASE_WRITE = "database:write"
    SUBPROCESS = "subprocess"
    SECRETS_READ = "secrets:read"
    TOOL_EXECUTE = "tool:execute"
    AGENT_INVOKE = "agent:invoke"
    HOOK_REGISTER = "hook:register"
    CONFIG_READ = "config:read"
    CONFIG_WRITE = "config:write"


class PluginDependency(BaseModel):
    """A dependency on another plugin."""

    name: str = Field(..., description="Plugin name (slug)")
    version_constraint: str = Field(
        default="*",
        description="SemVer constraint (e.g., '>=1.0.0', '^2.1.0', '~1.2.3').",
    )
    optional: bool = False


class PluginContributions(BaseModel):
    """Declares what a plugin contributes to the system."""

    skills: list[str] = Field(
        default_factory=list,
        description="Skill names this plugin provides.",
    )
    tools: list[str] = Field(
        default_factory=list,
        description="Tool class names or entry points this plugin provides.",
    )
    agents: list[str] = Field(
        default_factory=list,
        description="Agent definition file names this plugin provides.",
    )
    hooks: list[str] = Field(
        default_factory=list,
        description="Hook class names this plugin registers.",
    )


class PluginManifest(BaseModel):
    """Declarative metadata for a plugin, loaded before code execution.

    Analogous to SkillDefinition frontmatter but for the plugin unit.
    Supports YAML (plugin.yaml), TOML (plugin.toml), and Markdown (PLUGIN.md) formats.
    """

    # Identity
    name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9-]*$",
        description="Unique plugin slug.",
    )
    version: str = Field(
        ...,
        pattern=r"^\d+\.\d+\.\d+$",
        description="SemVer version string.",
    )
    description: str = Field(default="", max_length=500)
    author: str = ""
    license: str = ""
    homepage: str = ""
    repository: str = ""

    # Entry point
    entry_point: str = Field(
        default="plugin:Plugin",
        description=(
            "Python import path to the PluginBase subclass. "
            "Format: 'module_path:ClassName'. "
            "Default looks for Plugin class in plugin.py."
        ),
    )

    # What this plugin provides
    contributions: PluginContributions = Field(
        default_factory=PluginContributions,
    )

    # What this plugin needs
    permissions: list[PluginPermission] = Field(
        default_factory=list,
        description="System capabilities this plugin requires.",
    )

    # Dependencies
    dependencies: list[PluginDependency] = Field(
        default_factory=list,
        description="Other plugins this plugin depends on.",
    )

    # Lifecycle
    status: PluginStatus = Field(default=PluginStatus.ACTIVE)
    schema_version: str = Field(
        default="1",
        description="Manifest format version for future migration.",
    )

    # Tags for discovery
    tags: list[str] = Field(default_factory=list)
