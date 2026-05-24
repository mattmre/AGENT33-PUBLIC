from __future__ import annotations

import shutil
from pathlib import Path

from scripts.validate_policy_pack import validate_repo


ROOT = Path(__file__).resolve().parents[1]


def _copy_minimal_policy_tree(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    pack_dir = root / "core" / "packs" / "policy-pack-v1"
    pack_dir.mkdir(parents=True)
    for filename in (
        "AGENTS.md",
        "ORCHESTRATION.md",
        "EVIDENCE.md",
        "RISK_TRIGGERS.md",
        "ACCEPTANCE_CHECKS.md",
        "PROMOTION_GUIDE.md",
    ):
        shutil.copy2(ROOT / "core" / "packs" / "policy-pack-v1" / filename, pack_dir / filename)

    checklist_dir = root / "core" / "orchestrator" / "handoff"
    checklist_dir.mkdir(parents=True)
    shutil.copy2(ROOT / "core" / "orchestrator" / "handoff" / "REVIEW_CHECKLIST.md", checklist_dir / "REVIEW_CHECKLIST.md")

    workflows_dir = root / "core" / "workflows"
    workflows_dir.mkdir(parents=True)
    shutil.copy2(ROOT / "core" / "workflows" / "PROMOTION_CRITERIA.md", workflows_dir / "PROMOTION_CRITERIA.md")

    changelog = root / "core" / "CHANGELOG.md"
    changelog.write_text(
        "| Date | File | Change Type | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| 2026-05-24 | core/packs/policy-pack-v1 | closeout | policy-pack v1 closeout recorded. |\n",
        encoding="utf-8",
    )

    phase_dir = root / "_internal" / "phases"
    phase_dir.mkdir(parents=True)
    phase_dir.joinpath("PHASE-05-POLICY-PACK-AND-RISK-TRIGGERS.md").write_text(
        "# Phase 05\n",
        encoding="utf-8",
    )

    review_dir = root / "_internal" / "reviews"
    review_dir.mkdir(parents=True)
    review_dir.joinpath("phase-05-policy-pack-closeout-2026-05-24.md").write_text(
        "BHS score: 100\n"
        "BHS delta: 92 -> 100\n"
        "Ledger replacement: accepted\n"
        "Residual blockers: none\n",
        encoding="utf-8",
    )
    return root


def test_current_tree_policy_pack_validator_passes() -> None:
    assert validate_repo(ROOT) == []


def test_fixture_missing_trigger_family_fails(tmp_path: Path) -> None:
    root = _copy_minimal_policy_tree(tmp_path)
    checklist = root / "core" / "orchestrator" / "handoff" / "REVIEW_CHECKLIST.md"
    checklist.write_text(
        checklist.read_text(encoding="utf-8").replace(
            "- [ ] Supply chain changes (dependencies, lockfiles, build scripts)\n",
            "",
        ),
        encoding="utf-8",
    )

    findings = validate_repo(root)

    assert any(finding.code == "checklist-trigger-family-missing" for finding in findings)


def test_fixture_stale_p05_evidence_path_fails(tmp_path: Path) -> None:
    root = _copy_minimal_policy_tree(tmp_path)
    evidence = root / "_internal" / "reviews" / "phase-05-drift.md"
    evidence.write_text(
        "docs/session-logs/SESSION-2026-01-16_AGENT-33_PHASE-5.md\n",
        encoding="utf-8",
    )

    findings = validate_repo(root)

    assert any(finding.code == "stale-p05-evidence-path" for finding in findings)


def test_fixture_missing_closeout_fails(tmp_path: Path) -> None:
    root = _copy_minimal_policy_tree(tmp_path)
    (root / "_internal" / "reviews" / "phase-05-policy-pack-closeout-2026-05-24.md").unlink()

    findings = validate_repo(root)

    assert any(finding.code == "missing-p05-closeout" for finding in findings)
