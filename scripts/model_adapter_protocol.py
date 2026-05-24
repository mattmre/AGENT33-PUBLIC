#!/usr/bin/env python3
"""scripts/model_adapter_protocol.py -- v3.5 model-adapter contract surface.

Issue #10 (cluster D, 1/4). This module is the Python mirror of
docs/conventions/brutal-honesty-kit/v3.5/schemas/model-adapter-contract.schema.json:
TypedDict mirrors of `PlatformProfile` + `Capabilities` + `ArtifactManifest`
plus a `typing.Protocol` stub for `ModelAdapter` whose method bodies are
deliberately `...` (no-op contract surface) so that:

  * the Protocol can be `@runtime_checkable` against any concrete adapter
    a v3.6 / OCR_LOCAL implementation provides; AND
  * this PR ships the contract WITHOUT shipping any implementation.
    `pass` bodies that swallow `NotImplementedError` would be the lie
    pattern this very module exists to close. Methods declare `...` so
    isinstance() against the runtime_checkable Protocol still works
    while no production code accidentally relies on a stub.

Downstream consumers (cluster D rules R40+, cluster E orchestrator boot
packets) import the TypedDicts via:

    from scripts.model_adapter_protocol import PlatformProfile, ModelAdapter

The schema is the authoritative contract; this module exists so
mypy/pyright can type-check Python call sites without re-deriving the
field set from the JSON.
"""

from __future__ import annotations

from typing import (
    Dict,
    List,
    Literal,
    Optional,
    Protocol,
    TypedDict,
    runtime_checkable,
)


# --- Closed-set type aliases --------------------------------------------
# Every Literal mirrors a closed-set enum file under
# v3.5/docs/conventions/brutal-honesty-kit/v3.5/enums/. Drift between the
# Literal members here and the .txt enum files is caught by
# validate_v33_schema_drift.py::validate_platform_profile_parity.

CapabilityState = Literal["available", "unavailable", "unknown"]
"""Closed-set tri-state for every capability flag. `unknown` is NOT silently
treated as `available` -- downstream rules treat it as `unavailable` for
gating purposes (the L13 close)."""

PlatformName = Literal[
    "codex",
    "claude",
    "gemini",
    "copilot",
    "opencode",
    "unknown",
]
"""Closed-set platform identifier. Mirrors enums/platform-names.txt."""


# --- Capability map TypedDict -------------------------------------------
# Key set MUST equal capability-flags.txt as a set; the schema's
# capabilities.required mirrors the same list.

class Capabilities(TypedDict):
    """Per-dimension capability declaration. Every field is REQUIRED.

    Use ``CapabilityState`` literals for values; the schema's
    additionalProperties=false + required-keys list rejects any record
    missing a key or carrying an unknown key.
    """

    shell_access: CapabilityState
    filesystem_access: CapabilityState
    network_access: CapabilityState
    scm_access: CapabilityState
    browser_automation: CapabilityState
    spawn_fresh_agent: CapabilityState
    different_model_family: CapabilityState
    schedule_long_haul: CapabilityState
    approval_escalation: CapabilityState
    artifact_persistence: CapabilityState


# --- PlatformProfile TypedDict ------------------------------------------
# Key set MUST equal model-adapter-contract.schema.json properties as a
# set. Schema enforces additionalProperties=false.

class PlatformProfile(TypedDict, total=False):
    """A single PlatformProfile record. Required keys per the schema:

      * platform_name
      * capabilities
      * model_stack_present
      * degraded_mode

    Optional keys:

      * platform_version
      * model_family
      * degraded_reason   (REQUIRED + non-empty when degraded_mode=True;
                            enforced by the schema's allOf if/then clause)

    `total=False` so the TypedDict accepts records emitted before
    optional fields were filled in -- the schema is the runtime gate.
    """

    platform_name: PlatformName
    platform_version: Optional[str]
    model_family: Optional[str]
    capabilities: Capabilities
    model_stack_present: bool
    degraded_mode: bool
    degraded_reason: Optional[str]


# --- ArtifactManifest TypedDict -----------------------------------------
# Cluster-D #9 / #33 / #52 will extend this manifest shape (acquisition
# evidence, cache recipe, license chain). #10 ships only the base shape
# so downstream PRs can $ref into it.

class ArtifactManifest(TypedDict, total=False):
    """Per-artifact manifest entry. Cluster D #9/#33/#52 extend this with
    acquisition_evidence / cache_recipe / license_chain fields; #10
    ships only the base required fields."""

    artifact_id: str
    source_url: str
    revision: str
    hash_sha256: str
    license: Optional[str]
    acquired_at: str  # ISO-8601 UTC


# --- ModelAdapter Protocol ----------------------------------------------
# Contract surface ONLY. No implementation. Concrete adapters land in
# v3.6 / OCR_LOCAL. The `...` bodies are deliberate -- a `pass` body
# that swallowed NotImplementedError WOULD be the L4 pattern this
# module exists to close.

@runtime_checkable
class ModelAdapter(Protocol):
    """Contract for a per-platform adapter. Methods raise NotImplementedError
    in any concrete v3.5-shipped implementation; v3.6 / OCR_LOCAL ships
    the real adapters.

    Cluster D #9 / #33 / #52 extend this Protocol with model-cache /
    license-chain / provenance methods; #10 ships only the four base
    operations (acquire / verify / inventory / manifest).
    """

    def acquire(
        self,
        artifact_id: str,
        *,
        source_url: str,
        revision: str,
    ) -> ArtifactManifest:
        """Acquire an artifact from `source_url` at `revision`. Returns the
        manifest record (incl. sha256 + acquired_at timestamp) on success.
        Implementation MUST raise on hash mismatch / network failure; it
        MUST NOT silently return a partial manifest."""

        ...

    def verify(self, manifest: ArtifactManifest) -> bool:
        """Verify a manifest references an artifact still present + hash
        consistent. Returns True iff the artifact exists locally AND its
        sha256 matches the manifest. NEVER returns True on error;
        propagates the underlying exception so the caller sees the L13
        cause."""

        ...

    def inventory(self) -> List[ArtifactManifest]:
        """Return every manifest the adapter knows about. Order is not
        guaranteed; callers MUST sort by artifact_id when needed for
        deterministic comparison."""

        ...

    def manifest(self, artifact_id: str) -> ArtifactManifest:
        """Return the manifest for a single artifact. MUST raise
        KeyError on miss (NEVER returns a synthetic / placeholder
        manifest)."""

        ...


# --- Module-level constants --------------------------------------------
# Mirrors of the closed-set enums for runtime use (e.g. by R40 /
# detect_platform_profile.py / planted-drift tests). The .txt files
# remain authoritative.

CAPABILITY_FLAGS_CANONICAL = frozenset({
    "shell_access",
    "filesystem_access",
    "network_access",
    "scm_access",
    "browser_automation",
    "spawn_fresh_agent",
    "different_model_family",
    "schedule_long_haul",
    "approval_escalation",
    "artifact_persistence",
})

CAPABILITY_STATES_CANONICAL = frozenset({"available", "unavailable", "unknown"})

PLATFORM_NAMES_CANONICAL = frozenset({
    "codex",
    "claude",
    "gemini",
    "copilot",
    "opencode",
    "unknown",
})

REVIEW_SEPARATION_KINDS_CANONICAL = frozenset({
    "same-agent",
    "same-platform-fresh-agent",
    "different-model",
    "different-platform",
})


__all__ = [
    "ArtifactManifest",
    "Capabilities",
    "CAPABILITY_FLAGS_CANONICAL",
    "CAPABILITY_STATES_CANONICAL",
    "CapabilityState",
    "ModelAdapter",
    "PLATFORM_NAMES_CANONICAL",
    "PlatformName",
    "PlatformProfile",
    "REVIEW_SEPARATION_KINDS_CANONICAL",
]
