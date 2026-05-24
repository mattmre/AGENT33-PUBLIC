#!/usr/bin/env python3
"""Validate Phase 21 extensibility artifact relationships.

This is intentionally documentation-focused: Phase 21 is complete only when the
current artifacts exist, point at each other, and no longer depend on missing
legacy root files such as dedup-policy.md or sync-plan.md.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable


PHASE_DOC = "docs/architecture/PHASE-21-EXTENSIBILITY-PATTERNS-INTEGRATION.md"
CRITERIA_DOC = "docs/architecture/reviews/phase-criteria/phase-21.yaml"
CLOSEOUT_DOC = "docs/architecture/reviews/phase-21-extensibility-closeout-2026-05-24.md"

REQUIRED_PATHS = (
    PHASE_DOC,
    CRITERIA_DOC,
    CLOSEOUT_DOC,
    "docs/research/repo_dossiers/memorizer__petabridge__memorizer-v1.md",
    "docs/research/2026-01-20_memorizer-v1-integration-report.md",
    "core/orchestrator/RELATIONSHIP_TYPES.md",
    "core/agents/AGENT_MEMORY_PROTOCOL.md",
    "core/ARTIFACT_INDEX.md",
    "core/arch/CHANGE_EVENT_TYPES.md",
    "core/extensibility/REFINEMENT_RELATIONSHIP_POLICY.md",
    "core/orchestrator/distribution/DISTRIBUTION_SYNC_SPEC.md",
    "core/orchestrator/distribution/rules/example-sync-rule.yaml",
    "core/packs/policy-pack-v1/AGENTS.md",
)

P21_DOCS = (
    PHASE_DOC,
    "core/orchestrator/RELATIONSHIP_TYPES.md",
    "core/agents/AGENT_MEMORY_PROTOCOL.md",
    "core/arch/CHANGE_EVENT_TYPES.md",
    "core/extensibility/REFINEMENT_RELATIONSHIP_POLICY.md",
)

REQUIRED_TEXT = {
    PHASE_DOC: (
        "docs/research/repo_dossiers/memorizer__petabridge__memorizer-v1.md",
        "docs/research/2026-01-20_memorizer-v1-integration-report.md",
        "core/extensibility/REFINEMENT_RELATIONSHIP_POLICY.md",
        "core/orchestrator/distribution/DISTRIBUTION_SYNC_SPEC.md",
        "R-PHASE-21-1",
        "R-PHASE-21-6",
    ),
    "core/orchestrator/RELATIONSHIP_TYPES.md": (
        "derived-from",
        "supersedes",
        "core/extensibility/REFINEMENT_RELATIONSHIP_POLICY.md",
        "core/orchestrator/distribution/DISTRIBUTION_SYNC_SPEC.md",
    ),
    "core/agents/AGENT_MEMORY_PROTOCOL.md": (
        "core/orchestrator/RELATIONSHIP_TYPES.md",
        "core/ARTIFACT_INDEX.md",
        "core/extensibility/REFINEMENT_RELATIONSHIP_POLICY.md",
        "core/orchestrator/distribution/DISTRIBUTION_SYNC_SPEC.md",
    ),
    "core/ARTIFACT_INDEX.md": (
        "relationship-types",
        "agent-memory-protocol",
        "refinement-relationship-policy",
        "distribution-sync-spec",
        "change-event-types",
    ),
    "core/arch/CHANGE_EVENT_TYPES.md": (
        "core/extensibility/REFINEMENT_RELATIONSHIP_POLICY.md",
        "core/orchestrator/RELATIONSHIP_TYPES.md",
    ),
    "core/extensibility/REFINEMENT_RELATIONSHIP_POLICY.md": (
        "Captured source material under `collected/` is immutable.",
        "derived-from",
        "supersedes",
        "core/orchestrator/RELATIONSHIP_TYPES.md",
        "core/orchestrator/distribution/DISTRIBUTION_SYNC_SPEC.md",
    ),
    "core/packs/policy-pack-v1/AGENTS.md": (
        "core/agents/AGENT_MEMORY_PROTOCOL.md",
        "core/orchestrator/RELATIONSHIP_TYPES.md",
        "core/ARTIFACT_INDEX.md",
    ),
}

REQUIRED_RELATIONSHIP_TARGETS = (
    "docs/research/repo_dossiers/memorizer__petabridge__memorizer-v1.md",
    "docs/research/2026-01-20_memorizer-v1-integration-report.md",
    "core/orchestrator/RELATIONSHIP_TYPES.md",
    "core/agents/AGENT_MEMORY_PROTOCOL.md",
    "core/ARTIFACT_INDEX.md",
    "core/arch/CHANGE_EVENT_TYPES.md",
    "core/extensibility/REFINEMENT_RELATIONSHIP_POLICY.md",
    "core/orchestrator/distribution/DISTRIBUTION_SYNC_SPEC.md",
)

LEGACY_ROOT_FILES = ("dedup-policy.md", "sync-plan.md")
LEGACY_ALLOWED_MARKERS = (
    "invalid legacy",
    "historical root",
    "not a current artifact",
    "legacy p21 references",
)


def _read(root: Path, rel_path: str) -> str:
    return (root / rel_path).read_text(encoding="utf-8")


def _path_exists(root: Path, rel_path: str) -> bool:
    return (root / rel_path).exists()


def _validate_required_paths(root: Path, errors: list[str]) -> None:
    for rel_path in REQUIRED_PATHS:
        if not _path_exists(root, rel_path):
            errors.append(f"missing required P21 artifact: {rel_path}")


def _validate_required_text(root: Path, errors: list[str]) -> None:
    for rel_path, needles in REQUIRED_TEXT.items():
        if not _path_exists(root, rel_path):
            continue
        text = _read(root, rel_path)
        for needle in needles:
            if needle not in text:
                errors.append(f"{rel_path} missing required text: {needle}")


def _validate_legacy_paths(root: Path, errors: list[str]) -> None:
    for rel_path in P21_DOCS:
        if not _path_exists(root, rel_path):
            continue
        for line_no, line in enumerate(_read(root, rel_path).splitlines(), start=1):
            lowered = line.lower()
            if any(marker in lowered for marker in LEGACY_ALLOWED_MARKERS):
                continue
            for legacy in LEGACY_ROOT_FILES:
                if f"`{legacy}`" in line or re.search(rf"(^|\s){re.escape(legacy)}($|\s)", line):
                    errors.append(
                        f"{rel_path}:{line_no} references missing legacy root artifact {legacy}"
                    )


def _extract_relationship_targets(markdown: str) -> set[str]:
    targets: set[str] = set()
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 3:
            continue
        rel_type, target = cells[0], cells[1]
        if rel_type in {"Type", "---"} or not target:
            continue
        targets.add(target.strip("`"))
    return targets


def _validate_phase_relationships(root: Path, errors: list[str]) -> None:
    if not _path_exists(root, PHASE_DOC):
        return
    targets = _extract_relationship_targets(_read(root, PHASE_DOC))
    for target in REQUIRED_RELATIONSHIP_TARGETS:
        if target not in targets:
            errors.append(f"{PHASE_DOC} missing relationship target: {target}")
        elif target.endswith((".md", ".yaml", ".json")) and not _path_exists(root, target):
            errors.append(f"{PHASE_DOC} relationship target does not exist: {target}")


def _validate_criteria(root: Path, errors: list[str]) -> None:
    criteria_path = root / CRITERIA_DOC
    if not criteria_path.exists():
        return
    try:
        import yaml  # type: ignore
    except ImportError:
        errors.append("PyYAML is required to validate phase-21 criteria")
        return
    payload = yaml.safe_load(criteria_path.read_text(encoding="utf-8"))
    rows = payload.get("rows", []) if isinstance(payload, dict) else []
    expected_ids = {f"R-PHASE-21-{idx}" for idx in range(1, 7)}
    actual_ids = {row.get("requirement_id") for row in rows if isinstance(row, dict)}
    if actual_ids != expected_ids:
        errors.append(
            f"{CRITERIA_DOC} requirement ids mismatch: expected {sorted(expected_ids)}, got {sorted(actual_ids)}"
        )
    for row in rows:
        if not isinstance(row, dict):
            errors.append(f"{CRITERIA_DOC} contains a non-object row")
            continue
        if row.get("phase_id") != "PHASE-21":
            errors.append(f"{CRITERIA_DOC} row {row.get('requirement_id')} has wrong phase_id")
        if row.get("status") != "satisfied":
            errors.append(f"{CRITERIA_DOC} row {row.get('requirement_id')} is not satisfied")
        evidence = str(row.get("acceptance_evidence", ""))
        harness = str(row.get("test_harness_path", ""))
        if (
            "scripts/validate_phase21_artifact_relationships.py" not in evidence
            and harness != "scripts/validate_phase21_artifact_relationships.py"
            and row.get("requirement_id") != "R-PHASE-21-6"
        ):
            errors.append(
                f"{CRITERIA_DOC} row {row.get('requirement_id')} does not cite the artifact validator"
            )


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    _validate_required_paths(root, errors)
    _validate_required_text(root, errors)
    _validate_legacy_paths(root, errors)
    _validate_phase_relationships(root, errors)
    _validate_criteria(root, errors)
    return errors


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", help="Repository root to validate")
    args = parser.parse_args(list(argv) if argv is not None else None)

    root = Path(args.repo_root).resolve()
    errors = validate(root)
    if errors:
        print("validate_phase21_artifact_relationships: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("validate_phase21_artifact_relationships: PASS")
    print("validated required paths: 13")
    print("validated criteria rows: 6")
    print("validated relationship targets: 8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
