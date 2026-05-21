"""Starter and outcome pack manifest models.

Outcome packs are the beginner-facing layer over existing packs and workflows:
they describe what the pack does, what it needs, how it is governed, and which
workflow definitions can be launched from it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, field_validator, model_validator

from agent33.packs.models import PackGovernance
from agent33.packs.validation import (
    validate_pack_name,
    validate_relative_pack_path,
    validate_semver,
)
from agent33.workflows.definition import WorkflowDefinition  # noqa: TC001

if TYPE_CHECKING:
    from pathlib import Path


class OutcomePackKind(StrEnum):
    """Beginner-facing starter/outcome pack categories."""

    WORKFLOW_STARTER = "workflow-starter"
    IMPROVEMENT_LOOP = "improvement-loop"
    AUTOMATION_LOOP = "automation-loop"
    OUTCOME_PACK = "outcome-pack"


class OutcomePackDifficulty(StrEnum):
    """Presentation difficulty for progressive disclosure."""

    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class OutcomePackRequirementKind(StrEnum):
    """Requirement categories that readiness policy can evaluate later."""

    LLM = "llm"
    EMBEDDINGS = "embeddings"
    LOCAL_RUNTIME = "local-runtime"
    MCP = "mcp"
    TOOL = "tool"
    ENVIRONMENT = "environment"


class OutcomePackRiskLevel(StrEnum):
    """Starter pack risk levels used for first-run approval policy."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class OutcomePackTrustTier(StrEnum):
    """Simple trust tier displayed before install."""

    OFFICIAL = "official"
    VERIFIED = "verified"
    COMMUNITY = "community"
    IMPORTED = "imported"
    UNTRUSTED = "untrusted"


class OutcomePackWorkflow(BaseModel):
    """A workflow bundled with or referenced by an outcome pack."""

    name: str = Field(..., pattern=r"^[a-z][a-z0-9-]*$", min_length=2, max_length=64)
    description: str = Field(default="", max_length=500)
    path: str | None = Field(
        default=None,
        description="Relative path to a bundled workflow definition.",
    )
    definition: WorkflowDefinition | None = Field(
        default=None,
        description="Embedded workflow definition for atomic starter packs.",
    )
    required: bool = True

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return validate_relative_pack_path(value, field_name="Workflow path")

    @model_validator(mode="after")
    def _validate_source_present(self) -> OutcomePackWorkflow:
        if self.path is None and self.definition is None:
            raise ValueError("Outcome pack workflow must define either path or definition")
        if self.path is not None and self.definition is not None:
            raise ValueError("Outcome pack workflow cannot define both path and definition")
        if self.definition is not None and self.definition.name != self.name:
            raise ValueError(
                f"Embedded workflow name '{self.definition.name}' must match workflow "
                f"reference '{self.name}'"
            )
        return self


class OutcomePackPresentation(BaseModel):
    """Beginner-facing copy for pack cards and detail views."""

    title: str = Field(..., min_length=1, max_length=120)
    audience: str = Field(default="", max_length=120)
    summary: str = Field(..., min_length=1, max_length=500)
    difficulty: OutcomePackDifficulty = OutcomePackDifficulty.BEGINNER
    estimated_duration: str = Field(default="", max_length=80)
    expected_deliverables: list[str] = Field(default_factory=list)
    sample_inputs: dict[str, Any] = Field(default_factory=dict)


class OutcomePackCustomization(BaseModel):
    """Input defaults and restrictions for launching pack workflows."""

    required_inputs: list[str] = Field(default_factory=list)
    preset_values: dict[str, Any] = Field(default_factory=dict)
    locked_settings: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_no_preset_locked_conflicts(self) -> OutcomePackCustomization:
        conflicts = sorted(set(self.preset_values).intersection(self.locked_settings))
        if conflicts:
            joined = ", ".join(conflicts)
            raise ValueError(f"Preset values conflict with locked settings: {joined}")
        return self


class OutcomePackRequirement(BaseModel):
    """Provider, tool, MCP, or environment requirement for a starter pack."""

    kind: OutcomePackRequirementKind
    name: str = Field(..., min_length=1, max_length=80)
    required: bool = True
    preferences: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    setup_hint: str = Field(default="", max_length=300)

    @field_validator("preferences", "capabilities")
    @classmethod
    def _validate_unique_values(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("Requirement values must be unique")
        return values


class OutcomePackGovernance(BaseModel):
    """Outcome-pack-specific governance layered over existing pack governance."""

    pack: PackGovernance = Field(default_factory=PackGovernance)
    approval_required: bool = True
    risk_level: OutcomePackRiskLevel = OutcomePackRiskLevel.MEDIUM
    max_parallel_runs: int = Field(default=1, ge=1, le=32)
    max_daily_executions: int | None = Field(default=None, ge=1)
    allowed_models: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)


class OutcomePackProvenance(BaseModel):
    """Source and trust metadata displayed before install."""

    trust_tier: OutcomePackTrustTier = OutcomePackTrustTier.COMMUNITY
    source_url: str = Field(default="", max_length=500)
    license: str = Field(default="", max_length=80)
    signer_id: str = Field(default="", max_length=160)
    signature_algorithm: str = Field(default="", max_length=80)


class OutcomePackInstallation(BaseModel):
    """Setup and install behavior for a starter pack."""

    setup_steps: list[str] = Field(default_factory=list)
    required_runtime_features: list[str] = Field(default_factory=list)
    dry_run_supported: bool = True
    auto_enable: bool = False


class OutcomePackArtifact(BaseModel):
    """Expected artifact emitted by a pack-launched workflow."""

    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field(default="", max_length=300)
    drawer_section: str = Field(default="outcome", max_length=80)
    required: bool = False


class OutcomePackManifest(BaseModel):
    """Validated starter/outcome pack manifest."""

    schema_version: str = Field(default="1")
    name: str = Field(..., min_length=1, max_length=64)
    version: str = Field(..., min_length=1)
    kind: OutcomePackKind = OutcomePackKind.OUTCOME_PACK
    description: str = Field(..., min_length=1, max_length=500)
    author: str = Field(..., min_length=1)
    category: str = Field(default="", max_length=80)
    tags: list[str] = Field(default_factory=list)

    workflows: list[OutcomePackWorkflow] = Field(..., min_length=1)
    presentation: OutcomePackPresentation
    customization: OutcomePackCustomization = Field(default_factory=OutcomePackCustomization)
    requirements: list[OutcomePackRequirement] = Field(default_factory=list)
    governance: OutcomePackGovernance = Field(default_factory=OutcomePackGovernance)
    provenance: OutcomePackProvenance = Field(default_factory=OutcomePackProvenance)
    installation: OutcomePackInstallation = Field(default_factory=OutcomePackInstallation)
    artifacts: list[OutcomePackArtifact] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        if value != "1":
            raise ValueError(
                f"Unsupported outcome pack schema_version '{value}'. "
                "Only version '1' is supported."
            )
        return value

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return validate_pack_name(value, entity="Outcome pack")

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        return validate_semver(value, entity="Outcome pack")

    @model_validator(mode="after")
    def _validate_workflow_names_unique(self) -> OutcomePackManifest:
        names = [workflow.name for workflow in self.workflows]
        if len(names) != len(set(names)):
            duplicates = sorted({name for name in names if names.count(name) > 1})
            raise ValueError(
                f"Duplicate workflow names in outcome pack '{self.name}': {duplicates}"
            )
        return self

    @model_validator(mode="after")
    def _validate_required_inputs_exist_in_embedded_workflows(self) -> OutcomePackManifest:
        if not self.customization.required_inputs:
            return self

        embedded_inputs: set[str] = set()
        has_embedded_definition = False
        for workflow in self.workflows:
            if workflow.definition is None:
                continue
            has_embedded_definition = True
            embedded_inputs.update(workflow.definition.inputs.keys())

        if has_embedded_definition:
            missing = sorted(set(self.customization.required_inputs) - embedded_inputs)
            if missing:
                raise ValueError(
                    f"Required inputs are not present in embedded workflows: {', '.join(missing)}"
                )
        return self

    @model_validator(mode="after")
    def _validate_user_visible_fields_safe(self) -> OutcomePackManifest:
        from agent33.security.injection import scan_inputs_recursive

        scan_payload = self.model_dump(
            mode="json",
            exclude={"schema_version", "name", "version"},
        )
        result = scan_inputs_recursive(scan_payload)
        if not result.is_safe:
            threats = ", ".join(result.threats)
            raise ValueError(
                f"Outcome pack '{self.name}' failed injection scan: {threats}. "
                "Review and sanitize user-facing pack metadata before loading."
            )
        return self


def parse_outcome_pack_yaml(path: Path) -> OutcomePackManifest:
    """Parse an outcome pack YAML file and return a validated manifest."""
    import yaml

    if not path.is_file():
        raise FileNotFoundError(f"Outcome pack YAML not found: {path}")

    content = path.read_text(encoding="utf-8")
    try:
        raw = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError(f"Outcome pack YAML must be a mapping, got {type(raw).__name__}")

    return OutcomePackManifest.model_validate(raw)


def outcome_pack_to_dict(manifest: OutcomePackManifest) -> dict[str, Any]:
    """Serialize an outcome pack manifest for YAML/JSON output."""
    return manifest.model_dump(mode="json", exclude_defaults=True)
