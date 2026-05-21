"""Skill definition model for composable agent capabilities."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path  # noqa: TC003 — Pydantic needs Path at runtime for base_path field
from typing import Any

from pydantic import BaseModel, Field


class SkillStatus(StrEnum):
    """Lifecycle status for a skill definition."""

    ACTIVE = "active"
    DEPRECATED = "deprecated"
    EXPERIMENTAL = "experimental"


class SkillInvocationMode(StrEnum):
    """Who can trigger the skill."""

    USER_ONLY = "user-only"
    LLM_ONLY = "llm-only"
    BOTH = "both"


class SkillExecutionContext(StrEnum):
    """Where the skill runs."""

    INLINE = "inline"  # runs in agent's context
    FORK = "fork"  # runs in isolated subagent


class SkillDependency(BaseModel):
    """A dependency on another skill or tool."""

    name: str
    kind: str = "skill"  # "skill" or "tool"
    optional: bool = False


class SkillDefinition(BaseModel):
    """A composable capability module that can be attached to agents.

    Skills bundle domain knowledge (instructions), tool configurations,
    governance metadata, and optional artifacts into a single discoverable,
    loadable unit.
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Unique slug (e.g. 'kubernetes-deploy').",
    )
    version: str = Field(default="1.0.0")
    description: str = Field(
        default="",
        max_length=500,
        description="Short description (L0 metadata for context budget).",
    )
    instructions: str = Field(
        default="",
        description="Full markdown body (L1 content loaded on activation).",
    )

    # Tool configuration
    allowed_tools: list[str] = Field(
        default_factory=list,
        description="Tools this skill authorizes.",
    )
    disallowed_tools: list[str] = Field(
        default_factory=list,
        description="Tools this skill blocks.",
    )
    tool_parameter_defaults: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Per-tool parameter overrides when skill is active.",
    )

    # Governance
    invocation_mode: SkillInvocationMode = Field(
        default=SkillInvocationMode.BOTH,
    )
    execution_context: SkillExecutionContext = Field(
        default=SkillExecutionContext.INLINE,
    )
    autonomy_level: str | None = Field(
        default=None,
        description="Override agent's autonomy when skill is active.",
    )
    approval_required_for: list[str] = Field(
        default_factory=list,
        description="Patterns requiring human approval.",
    )

    # Artifacts
    scripts_dir: str | None = Field(
        default=None,
        description="Relative path to bundled scripts.",
    )
    templates_dir: str | None = Field(
        default=None,
        description="Relative path to templates.",
    )
    references: list[str] = Field(
        default_factory=list,
        description="Relative paths to reference files.",
    )

    # Metadata
    tags: list[str] = Field(default_factory=list)
    category: str = ""
    provenance: str = ""
    author: str = ""
    status: SkillStatus = Field(default=SkillStatus.ACTIVE)
    dependencies: list[SkillDependency] = Field(default_factory=list)
    schema_version: str = Field(
        default="1",
        description="Skill format version for migration.",
    )

    # Slash-command metadata (Phase 54)
    command_name: str | None = Field(
        default=None,
        max_length=64,
        description="Custom slash-command name (without /). Auto-derived if not set.",
    )
    command_help: str = Field(
        default="",
        max_length=200,
        description="Short help text shown in /commands listing.",
    )

    # Supporting files (populated during loading, not from file)
    supporting_files: list[str] = Field(
        default_factory=list,
        description="Relative paths to supporting files discovered under the skill directory.",
    )

    # Runtime (set during loading, not from file)
    base_path: Path | None = Field(
        default=None,
        exclude=True,
        description="Resolved directory containing this skill.",
    )
