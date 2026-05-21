"""Regression coverage for official Wave 10 outcome pack seeds."""

from __future__ import annotations

from pathlib import Path

from agent33.packs.loader import load_pack_manifest
from agent33.packs.outcome_pack import parse_outcome_pack_yaml
from agent33.workflows.definition import WorkflowDefinition

OFFICIAL_PACK_DIR = Path(__file__).resolve().parents[1] / "packs" / "official-outcome-packs"


def test_official_outcome_pack_manifest_references_five_seed_packs() -> None:
    manifest = load_pack_manifest(OFFICIAL_PACK_DIR)

    assert manifest.name == "official-outcome-packs"
    assert [entry.path for entry in manifest.outcome_packs] == [
        "outcomes/founder-mvp-builder.yaml",
        "outcomes/competitor-research-brief.yaml",
        "outcomes/repository-security-review.yaml",
        "outcomes/test-generation-sprint.yaml",
        "outcomes/release-readiness-checklist.yaml",
    ]


def test_official_outcome_pack_yaml_and_workflows_validate() -> None:
    manifest = load_pack_manifest(OFFICIAL_PACK_DIR)

    for entry in manifest.outcome_packs:
        outcome = parse_outcome_pack_yaml(OFFICIAL_PACK_DIR / entry.path)

        assert outcome.provenance.trust_tier == "official"
        assert outcome.governance.approval_required is True
        assert outcome.installation.auto_enable is False
        assert outcome.installation.dry_run_supported is True
        assert outcome.presentation.expected_deliverables
        assert outcome.artifacts

        for workflow_ref in outcome.workflows:
            assert workflow_ref.path is not None
            workflow = WorkflowDefinition.load_from_file(OFFICIAL_PACK_DIR / workflow_ref.path)

            assert workflow.name == workflow_ref.name
            assert workflow.inputs
            assert workflow.outputs
            assert workflow.steps
