"""Readiness and beginner-safe policy evaluation for outcome packs."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from agent33.packs.outcome_pack import (
    OutcomePackManifest,
    OutcomePackRequirement,
    OutcomePackRequirementKind,
    OutcomePackRiskLevel,
    OutcomePackTrustTier,
)


class OutcomePackReadinessState(StrEnum):
    """Overall readiness state for installing or running an outcome pack."""

    READY = "ready"
    NEEDS_SETUP = "needs_setup"
    REVIEW_REQUIRED = "review_required"
    BLOCKED = "blocked"


class OutcomePackRequirementState(StrEnum):
    """Readiness state for one outcome pack requirement."""

    READY = "ready"
    MISSING = "missing"
    OPTIONAL_MISSING = "optional_missing"
    BLOCKED = "blocked"


class OutcomePackReadinessContext(BaseModel):
    """Runtime facts used to evaluate pack readiness.

    The evaluator stays dependency-light for this slice. Later routes/services can
    build this context from model health, MCP, tool, and environment registries.
    """

    available: dict[OutcomePackRequirementKind, list[str]] = Field(default_factory=dict)
    blocked: dict[OutcomePackRequirementKind, list[str]] = Field(default_factory=dict)
    beginner_mode: bool = True
    approval_granted: bool = False
    allow_imported: bool = False


class OutcomePackRequirementReadiness(BaseModel):
    """Result for one requirement."""

    kind: OutcomePackRequirementKind
    name: str
    required: bool
    state: OutcomePackRequirementState
    blocking: bool
    matched: list[str] = Field(default_factory=list)
    message: str
    next_step: str = ""


class OutcomePackReadinessResult(BaseModel):
    """Complete readiness assessment for an outcome pack."""

    pack_name: str
    version: str
    state: OutcomePackReadinessState
    can_install: bool
    can_run: bool
    approval_required: bool
    approval_satisfied: bool
    trust_tier: OutcomePackTrustTier
    risk_level: OutcomePackRiskLevel
    requirement_results: list[OutcomePackRequirementReadiness] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class OutcomePackReadinessEvaluator:
    """Evaluate whether an outcome pack is safe and ready to install/run."""

    def evaluate(
        self,
        manifest: OutcomePackManifest,
        context: OutcomePackReadinessContext | None = None,
    ) -> OutcomePackReadinessResult:
        """Return a beginner-safe readiness decision for an outcome pack."""
        context = context or OutcomePackReadinessContext()
        requirement_results = [
            self._evaluate_requirement(requirement, context)
            for requirement in manifest.requirements
        ]

        blocking_reasons: list[str] = []
        next_steps: list[str] = []

        trust_block = self._trust_block_reason(manifest.provenance.trust_tier, context)
        if trust_block:
            blocking_reasons.append(trust_block)
            next_steps.append("Choose an official or verified pack, or request admin review.")

        for result in requirement_results:
            if result.blocking:
                blocking_reasons.append(result.message)
            if result.next_step and result.state != OutcomePackRequirementState.READY:
                next_steps.append(result.next_step)

        approval_required = self._requires_approval(manifest, context)
        approval_satisfied = not approval_required or context.approval_granted
        if approval_required and not approval_satisfied:
            next_steps.append("Request review before running this outcome pack.")

        has_missing_setup = any(
            result.state
            in {
                OutcomePackRequirementState.MISSING,
                OutcomePackRequirementState.OPTIONAL_MISSING,
            }
            for result in requirement_results
        )
        has_blocking_requirement = any(result.blocking for result in requirement_results)

        can_install = not trust_block
        can_run = can_install and not has_blocking_requirement and approval_satisfied
        state = self._overall_state(
            trust_block=trust_block,
            has_blocking_requirement=has_blocking_requirement,
            has_missing_setup=has_missing_setup,
            approval_required=approval_required,
            approval_satisfied=approval_satisfied,
        )

        if not next_steps and state == OutcomePackReadinessState.READY:
            next_steps.append("This outcome pack is ready to install and run.")

        return OutcomePackReadinessResult(
            pack_name=manifest.name,
            version=manifest.version,
            state=state,
            can_install=can_install,
            can_run=can_run,
            approval_required=approval_required,
            approval_satisfied=approval_satisfied,
            trust_tier=manifest.provenance.trust_tier,
            risk_level=manifest.governance.risk_level,
            requirement_results=requirement_results,
            blocking_reasons=blocking_reasons,
            next_steps=self._dedupe(next_steps),
        )

    def _evaluate_requirement(
        self,
        requirement: OutcomePackRequirement,
        context: OutcomePackReadinessContext,
    ) -> OutcomePackRequirementReadiness:
        candidates = [requirement.name, *requirement.preferences]
        available = set(context.available.get(requirement.kind, []))
        blocked = set(context.blocked.get(requirement.kind, []))

        blocked_matches = [candidate for candidate in candidates if candidate in blocked]
        if blocked_matches:
            return OutcomePackRequirementReadiness(
                kind=requirement.kind,
                name=requirement.name,
                required=requirement.required,
                state=OutcomePackRequirementState.BLOCKED,
                blocking=True,
                matched=blocked_matches,
                message=(
                    f"{self._label(requirement.kind)} requirement '{requirement.name}' "
                    "is blocked by policy."
                ),
                next_step="Ask an administrator to approve or replace the blocked requirement.",
            )

        matched = [candidate for candidate in candidates if candidate in available]
        if matched:
            return OutcomePackRequirementReadiness(
                kind=requirement.kind,
                name=requirement.name,
                required=requirement.required,
                state=OutcomePackRequirementState.READY,
                blocking=False,
                matched=matched,
                message=(
                    f"{self._label(requirement.kind)} requirement '{requirement.name}' is ready."
                ),
            )

        state = (
            OutcomePackRequirementState.MISSING
            if requirement.required
            else OutcomePackRequirementState.OPTIONAL_MISSING
        )
        return OutcomePackRequirementReadiness(
            kind=requirement.kind,
            name=requirement.name,
            required=requirement.required,
            state=state,
            blocking=requirement.required,
            message=(
                f"{self._label(requirement.kind)} requirement '{requirement.name}' is missing."
            ),
            next_step=requirement.setup_hint
            or f"Configure {self._label(requirement.kind).lower()} '{requirement.name}'.",
        )

    def _requires_approval(
        self,
        manifest: OutcomePackManifest,
        context: OutcomePackReadinessContext,
    ) -> bool:
        if manifest.governance.approval_required:
            return True
        if manifest.provenance.trust_tier in {
            OutcomePackTrustTier.COMMUNITY,
            OutcomePackTrustTier.IMPORTED,
        }:
            return True
        return context.beginner_mode and (
            manifest.provenance.trust_tier != OutcomePackTrustTier.OFFICIAL
            or manifest.governance.risk_level != OutcomePackRiskLevel.LOW
        )

    def _trust_block_reason(
        self,
        trust_tier: OutcomePackTrustTier,
        context: OutcomePackReadinessContext,
    ) -> str:
        if trust_tier == OutcomePackTrustTier.UNTRUSTED:
            return "Outcome pack is untrusted and cannot be installed or run."
        if trust_tier == OutcomePackTrustTier.IMPORTED and not context.allow_imported:
            return "Imported outcome packs require explicit imported-pack allowance."
        return ""

    def _overall_state(
        self,
        *,
        trust_block: str,
        has_blocking_requirement: bool,
        has_missing_setup: bool,
        approval_required: bool,
        approval_satisfied: bool,
    ) -> OutcomePackReadinessState:
        if trust_block or has_blocking_requirement:
            return OutcomePackReadinessState.BLOCKED
        if approval_required and not approval_satisfied:
            return OutcomePackReadinessState.REVIEW_REQUIRED
        if has_missing_setup:
            return OutcomePackReadinessState.NEEDS_SETUP
        return OutcomePackReadinessState.READY

    def _label(self, kind: OutcomePackRequirementKind) -> str:
        return {
            OutcomePackRequirementKind.LLM: "LLM",
            OutcomePackRequirementKind.EMBEDDINGS: "Embeddings",
            OutcomePackRequirementKind.LOCAL_RUNTIME: "Local runtime",
            OutcomePackRequirementKind.MCP: "MCP",
            OutcomePackRequirementKind.TOOL: "Tool",
            OutcomePackRequirementKind.ENVIRONMENT: "Environment",
        }[kind]

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            deduped.append(value)
        return deduped
