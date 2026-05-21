"""Support bundle contracts."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class SupportBundleSection(StrEnum):
    DIAGNOSTICS = "diagnostics"
    LOGS = "logs"
    CONFIG = "config"
    RUNS = "runs"
    RESOURCES = "resources"


class SupportBundleRequest(BaseModel):
    bundle_id: str
    include_sections: list[SupportBundleSection]
    redact_secrets: bool = True


class SupportBundleManifest(BaseModel):
    bundle_id: str
    sections: list[SupportBundleSection]
    redacted: bool
    files: list[str] = Field(default_factory=list)


def build_support_bundle_manifest(
    request: SupportBundleRequest,
) -> SupportBundleManifest:
    files = [f"{section.value}.json" for section in request.include_sections]
    if request.redact_secrets:
        files.append("redaction-report.json")
    return SupportBundleManifest(
        bundle_id=request.bundle_id,
        sections=list(request.include_sections),
        redacted=request.redact_secrets,
        files=files,
    )
