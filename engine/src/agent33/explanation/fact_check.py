"""Fact-check criteria hooks for explanation scaffolding."""

from __future__ import annotations

from pathlib import Path

import structlog

from agent33.explanation.models import (
    ClaimType,
    ExplanationClaim,
    ExplanationMetadata,
    FactCheckStatus,
)

logger = structlog.get_logger()


async def run_fact_check_hooks(explanation: ExplanationMetadata) -> FactCheckStatus:
    """Run stage-1 fact-check hooks and return the aggregate status.

    Stage 2 adds deterministic claim validation while preserving Stage 1
    fallback behavior when no claims are provided.
    """
    logger.info(
        "fact_check_hook_invoked",
        explanation_id=explanation.id,
        entity_type=explanation.entity_type,
        entity_id=explanation.entity_id,
        claims=len(explanation.claims),
    )

    if not explanation.claims:
        return FactCheckStatus.SKIPPED

    for claim in explanation.claims:
        _validate_claim(explanation, claim)

    if any(claim.status == FactCheckStatus.FLAGGED for claim in explanation.claims):
        return FactCheckStatus.FLAGGED
    if all(claim.status == FactCheckStatus.VERIFIED for claim in explanation.claims):
        return FactCheckStatus.VERIFIED
    return FactCheckStatus.PENDING


def _validate_claim(explanation: ExplanationMetadata, claim: ExplanationClaim) -> None:
    if claim.claim_type == ClaimType.FILE_EXISTS:
        _validate_file_exists(explanation, claim)
        return
    if claim.claim_type == ClaimType.METADATA_EQUALS:
        actual = explanation.metadata.get(claim.target)
        claim.actual = "" if actual is None else str(actual)
        if claim.actual == claim.expected:
            claim.status = FactCheckStatus.VERIFIED
            claim.message = "Metadata value matches expected value"
            return
        claim.status = FactCheckStatus.FLAGGED
        claim.message = "Metadata value does not match expected value"
        return
    if claim.claim_type == ClaimType.CONTENT_CONTAINS:
        claim.actual = explanation.content
        if claim.expected and claim.expected in explanation.content:
            claim.status = FactCheckStatus.VERIFIED
            claim.message = "Explanation content contains expected text"
            return
        claim.status = FactCheckStatus.FLAGGED
        claim.message = "Explanation content missing expected text"
        return

    claim.status = FactCheckStatus.PENDING
    claim.message = "No validator available for claim type"


def _validate_file_exists(explanation: ExplanationMetadata, claim: ExplanationClaim) -> None:
    if "\x00" in claim.target:
        claim.status = FactCheckStatus.FLAGGED
        claim.actual = ""
        claim.message = "Invalid file path"
        return

    base_root = Path(str(explanation.metadata.get("repo_root", ".")))
    target_path = Path(claim.target)
    if not target_path.is_absolute():
        target_path = base_root / target_path

    resolved = target_path.resolve()
    claim.actual = str(resolved)
    if resolved.exists():
        claim.status = FactCheckStatus.VERIFIED
        claim.message = "File exists"
        return

    claim.status = FactCheckStatus.FLAGGED
    claim.message = "File does not exist"
