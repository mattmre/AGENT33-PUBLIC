"""Resource manifest schema for installable AGENT33 assets."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class ResourceKind(StrEnum):
    PACK = "pack"
    PLUGIN = "plugin"
    SKILL = "skill"
    WORKFLOW = "workflow"
    PROMPT = "prompt"
    POLICY = "policy"
    EVAL = "eval"
    DATASET = "dataset"
    ENVIRONMENT = "environment"


class ResourcePermission(BaseModel):
    scope: str
    reason: str = ""
    required: bool = True


class ResourceCompatibility(BaseModel):
    min_agent33_version: str = ""
    max_agent33_version: str = ""
    platforms: list[str] = Field(default_factory=list)
    requires: list[str] = Field(default_factory=list)


class ResourceTrust(BaseModel):
    publisher: str = ""
    source_url: str = ""
    sha256: str = ""
    signature: str = ""
    verified: bool = False


class ResourceRollback(BaseModel):
    supported: bool = True
    instructions: list[str] = Field(default_factory=list)


class ResourceManifest(BaseModel):
    id: str
    name: str
    version: str
    kind: ResourceKind
    description: str = ""
    entrypoint: str = ""
    permissions: list[ResourcePermission] = Field(default_factory=list)
    compatibility: ResourceCompatibility = Field(default_factory=ResourceCompatibility)
    trust: ResourceTrust = Field(default_factory=ResourceTrust)
    rollback: ResourceRollback = Field(default_factory=ResourceRollback)
    tags: list[str] = Field(default_factory=list)

    @field_validator("id", "name", "version")
    @classmethod
    def _must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, value: list[str]) -> list[str]:
        return sorted({item.strip().lower() for item in value if item.strip()})


def validate_resource_manifest(payload: object) -> ResourceManifest:
    """Validate arbitrary payload into a ResourceManifest."""
    return ResourceManifest.model_validate(payload)
