from __future__ import annotations

from pathlib import Path

import pytest

from scripts.validate_phase21_artifact_relationships import validate


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_phase21_artifact_relationships_are_current() -> None:
    assert validate(REPO_ROOT) == []


def test_phase21_validator_detects_missing_relationship_policy(tmp_path: Path) -> None:
    for source in (
        "docs/architecture/PHASE-21-EXTENSIBILITY-PATTERNS-INTEGRATION.md",
        "docs/architecture/reviews/phase-criteria/phase-21.yaml",
        "docs/architecture/reviews/phase-21-extensibility-closeout-2026-05-24.md",
        "core/orchestrator/RELATIONSHIP_TYPES.md",
        "core/agents/AGENT_MEMORY_PROTOCOL.md",
        "core/ARTIFACT_INDEX.md",
        "core/arch/CHANGE_EVENT_TYPES.md",
        "core/orchestrator/distribution/DISTRIBUTION_SYNC_SPEC.md",
        "core/orchestrator/distribution/rules/example-sync-rule.yaml",
        "core/packs/policy-pack-v1/AGENTS.md",
        "docs/research/repo_dossiers/memorizer__petabridge__memorizer-v1.md",
        "docs/research/2026-01-20_memorizer-v1-integration-report.md",
    ):
        target = tmp_path / source
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((REPO_ROOT / source).read_text(encoding="utf-8"), encoding="utf-8")

    errors = validate(tmp_path)

    assert "missing required P21 artifact: core/extensibility/REFINEMENT_RELATIONSHIP_POLICY.md" in errors
