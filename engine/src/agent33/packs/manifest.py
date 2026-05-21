"""Pack manifest (PACK.yaml) parsing and validation.

A Skill Pack is a directory containing a PACK.yaml manifest and one or
more skill definitions.  The manifest is the pack's identity document.

Since P-PACK v1, manifests may also contain *improvement pack* sections:
``prompt_addenda`` (text appended to agent system prompts) and
``tool_config`` (per-tool parameter defaults / policy overrides).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, field_validator, model_validator

from agent33.packs.models import (
    OutcomePackEntry,
    PackCompatibility,
    PackDependency,
    PackGovernance,
    PackSkillEntry,
)
from agent33.packs.validation import validate_pack_name, validate_semver

if TYPE_CHECKING:
    from pathlib import Path

import structlog

logger = structlog.get_logger()


class PackDependencies(BaseModel):
    """Dependencies section of a pack manifest."""

    packs: list[PackDependency] = Field(default_factory=list)
    engine: dict[str, str] = Field(
        default_factory=dict,
        description="Engine compatibility: {min_version: '0.1.0'}",
    )
    plugins: list[PackDependency] = Field(default_factory=list)


class PackManifest(BaseModel):
    """Parsed and validated PACK.yaml manifest.

    This model represents the on-disk manifest format.  After validation,
    it is converted to an ``InstalledPack`` for use in the registry.
    """

    schema_version: str = Field(
        default="1",
        description="Manifest format version (currently '1')",
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Pack slug (lowercase, hyphens, 1-64 chars)",
    )
    version: str = Field(
        ...,
        min_length=1,
        description="Semver version (MAJOR.MINOR.PATCH)",
    )
    description: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Short description",
    )
    author: str = Field(
        ...,
        min_length=1,
        description="Author or organization name",
    )
    license: str = ""
    homepage: str = ""
    repository: str = ""

    # Classification
    tags: list[str] = Field(default_factory=list)
    category: str = ""

    # Skills
    skills: list[PackSkillEntry] = Field(
        ...,
        min_length=1,
        description="Skills included in this pack (at least one required)",
    )

    # Dependencies
    dependencies: PackDependencies = Field(default_factory=PackDependencies)

    # Compatibility
    compatibility: PackCompatibility = Field(default_factory=PackCompatibility)

    # Governance
    governance: PackGovernance = Field(default_factory=PackGovernance)

    # --- Improvement pack sections (P-PACK v1) ---
    prompt_addenda: list[str] = Field(
        default_factory=list,
        description="Text sections to append to agent system prompt when the pack is active.",
    )
    tool_config: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Per-tool parameter defaults and policy overrides.",
    )
    outcome_packs: list[OutcomePackEntry] = Field(
        default_factory=list,
        description="Starter/outcome pack manifests bundled with this skill pack.",
    )

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return validate_pack_name(value)

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        return validate_semver(value)

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        if value != "1":
            raise ValueError(
                f"Unsupported schema_version '{value}'. Only version '1' is supported."
            )
        return value

    @model_validator(mode="after")
    def _validate_skill_names_unique(self) -> PackManifest:
        """Ensure no duplicate skill names within a pack."""
        seen: set[str] = set()
        for skill in self.skills:
            if skill.name in seen:
                raise ValueError(f"Duplicate skill name '{skill.name}' in pack '{self.name}'")
            seen.add(skill.name)
        return self

    @model_validator(mode="after")
    def _validate_prompt_addenda_safe(self) -> PackManifest:
        """Reject packs whose prompt_addenda contain injection patterns."""
        if not self.prompt_addenda:
            return self

        from agent33.security.injection import scan_inputs_recursive

        result = scan_inputs_recursive(self.prompt_addenda)
        if not result.is_safe:
            threats = ", ".join(result.threats)
            raise ValueError(
                f"Prompt addenda in pack '{self.name}' failed injection scan: {threats}. "
                f"Review and sanitize the addenda before loading."
            )
        return self

    @model_validator(mode="after")
    def _validate_tool_config_safe(self) -> PackManifest:
        """Reject packs whose tool_config contains injection patterns."""
        if not self.tool_config:
            return self

        from agent33.security.injection import scan_inputs_recursive

        result = scan_inputs_recursive(self.tool_config)
        if not result.is_safe:
            threats = ", ".join(result.threats)
            raise ValueError(
                f"Tool config in pack '{self.name}' failed injection scan: {threats}. "
                f"Review and sanitize the tool configuration before loading."
            )
        return self

    @model_validator(mode="after")
    def _validate_outcome_pack_paths_unique(self) -> PackManifest:
        """Ensure bundled outcome pack references do not collide."""
        paths = [entry.path for entry in self.outcome_packs]
        if len(paths) != len(set(paths)):
            duplicates = sorted({path for path in paths if paths.count(path) > 1})
            raise ValueError(f"Duplicate outcome pack paths in pack '{self.name}': {duplicates}")
        return self


def parse_pack_yaml(path: Path) -> PackManifest:
    """Parse a PACK.yaml file and return a validated PackManifest.

    Args:
        path: Path to the PACK.yaml file.

    Returns:
        A validated PackManifest instance.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the YAML is invalid or fails validation.
    """
    import yaml

    if not path.is_file():
        raise FileNotFoundError(f"PACK.yaml not found: {path}")

    content = path.read_text(encoding="utf-8")

    try:
        raw = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError(f"PACK.yaml must be a YAML mapping, got {type(raw).__name__}")

    return PackManifest.model_validate(raw)


def manifest_to_dict(manifest: PackManifest) -> dict[str, Any]:
    """Serialize a manifest to a dictionary suitable for YAML output."""
    return manifest.model_dump(mode="json", exclude_defaults=True)
