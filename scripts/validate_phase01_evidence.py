#!/usr/bin/env python3
"""Validate Phase 01 inventory/collision/stale-path evidence.

This checker is deliberately narrow. It does not prove historical raw repo
coverage; it verifies that Phase 01's current evidence does not claim that
coverage, that the zero-state manifest matches the checkout, and that current
P01 dependencies do not point at retired legacy paths.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - dependency is present for criteria compiler
    yaml = None


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/architecture/reviews/phase-01-current-inventory-manifest-2026-05-24.json"
CRITERIA = ROOT / "docs/architecture/reviews/phase-criteria/phase-01.yaml"
PHASE_DOC = ROOT / "docs/architecture/PHASE-01-FOUNDATION-AND-INVENTORY.md"
EVIDENCE = ROOT / "docs/architecture/reviews/phase-01-inventory-collision-evidence-2026-05-24.md"
CLOSEOUT = ROOT / "docs/architecture/reviews/phase-01-foundation-inventory-closeout-2026-05-24.md"
CHANGELOG = ROOT / "core/CHANGELOG.md"

SCAN_ROOTS = [
    Path("collected"),
    Path("core/arch"),
    Path("core/agents"),
    Path("core/prompts"),
    Path("core/workflows"),
    Path("docs/research/repo_dossiers"),
]

DUPLICATE_SUFFIX_RE = re.compile(
    r"(?i)(?:\s-\scopy|\scopy|\s\(\d+\)|\.(?:bak|orig|old|tmp)|~$)"
)

EXPECTED_CHANGELOG_SNIPPETS = [
    "core/arch/* (AEP templates & guides)",
    "core/prompts/agentic-review-framework.md",
    "core/prompts/agentic-review-prompts.md",
    "core/agents/CLAUDE.md",
    "core/agents/AGENTS.md",
    "core/orchestrator/*",
    "core/workflows/*",
    "core/workflows/instructions/csharp.instructions.md",
    "core/workflows/instructions/python.instructions.md",
]


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def sorted_child_names(path: Path, want_dirs: bool) -> list[str]:
    return sorted(
        child.name
        for child in path.iterdir()
        if child.is_dir() == want_dirs
    )


def sorted_files(path: Path, suffix: str | None = None) -> list[str]:
    files = []
    for child in path.iterdir():
        if child.is_file() and (suffix is None or child.name.endswith(suffix)):
            files.append(child.name)
    return sorted(files)


def scan_duplicate_suffixes() -> list[str]:
    matches: list[str] = []
    for scan_root in SCAN_ROOTS:
        absolute = ROOT / scan_root
        if not absolute.exists():
            continue
        for path in absolute.rglob("*"):
            if path.is_file() and DUPLICATE_SUFFIX_RE.search(path.name):
                matches.append(rel(path))
    return sorted(matches)


def main() -> int:
    failures: list[str] = []

    for path in [MANIFEST, CRITERIA, PHASE_DOC, EVIDENCE, CLOSEOUT, CHANGELOG]:
        if not path.exists():
            failures.append(f"missing required P01 artifact: {rel(path)}")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1

    manifest = load_json(MANIFEST)

    if manifest.get("raw_repo_coverage_claimed") is not False:
        failures.append("manifest must explicitly avoid claiming raw repo coverage")

    collected = ROOT / "collected"
    collected_manifest = manifest["collected"]
    actual_collected_dirs = sorted_child_names(collected, want_dirs=True)
    actual_collected_files = sorted_child_names(collected, want_dirs=False)
    if actual_collected_dirs != collected_manifest["directories"]:
        failures.append(
            "collected directory list drift: "
            f"actual={actual_collected_dirs!r} manifest={collected_manifest['directories']!r}"
        )
    if actual_collected_files != collected_manifest["files"]:
        failures.append(
            "collected file list drift: "
            f"actual={actual_collected_files!r} manifest={collected_manifest['files']!r}"
        )
    if collected_manifest["directory_count"] != len(actual_collected_dirs):
        failures.append("collected directory_count does not match filesystem")
    if collected_manifest["file_count"] != len(actual_collected_files):
        failures.append("collected file_count does not match filesystem")

    dossiers = ROOT / manifest["structured_dossiers"]["path"]
    actual_dossiers = sorted_files(dossiers, ".md")
    if actual_dossiers != manifest["structured_dossiers"]["files"]:
        failures.append("structured dossier file list drift")
    if manifest["structured_dossiers"]["file_count"] != len(actual_dossiers):
        failures.append("structured dossier file_count does not match filesystem")

    retired_paths = {item["path"] for item in manifest["retired_legacy_expectations"]}
    dependency_paths = set(manifest["current_dependency_paths"])
    stale_dependencies = sorted(retired_paths & dependency_paths)
    if stale_dependencies:
        failures.append(f"retired legacy path(s) still listed as current dependencies: {stale_dependencies}")

    for dependency in sorted(dependency_paths):
        if not (ROOT / dependency).exists():
            failures.append(f"current dependency path does not exist: {dependency}")

    for retired in sorted(retired_paths):
        if (ROOT / retired).exists():
            failures.append(f"retired legacy path unexpectedly exists and needs reclassification: {retired}")

    actual_duplicate_suffixes = scan_duplicate_suffixes()
    expected_duplicate_suffixes = manifest["collision_scan"]["duplicate_suffix_matches"]
    if actual_duplicate_suffixes != expected_duplicate_suffixes:
        failures.append(
            "duplicate/copy/backup suffix scan drift: "
            f"actual={actual_duplicate_suffixes!r} manifest={expected_duplicate_suffixes!r}"
        )

    namespace_paths = {
        item["path"] for item in manifest["collision_scan"]["namespace_encoded_names"]
    }
    for namespace_path in namespace_paths:
        if not (ROOT / namespace_path).exists():
            failures.append(f"namespace-encoded collision classification path missing: {namespace_path}")

    changelog_text = CHANGELOG.read_text(encoding="utf-8")
    for snippet in EXPECTED_CHANGELOG_SNIPPETS:
        if snippet not in changelog_text:
            failures.append(f"historical canonicalization snippet missing from core/CHANGELOG.md: {snippet}")

    if yaml is None:
        failures.append("PyYAML is unavailable, cannot inspect compiled phase criteria")
    else:
        criteria = yaml.safe_load(CRITERIA.read_text(encoding="utf-8"))
        for row in criteria.get("rows", []):
            if row.get("phase_id") == "PHASE-01" and row.get("status") != "satisfied":
                failures.append(f"criteria row is not satisfied: {row.get('requirement_id')}")
            if row.get("phase_id") == "PHASE-01" and row.get("blocker_type") is not None:
                failures.append(f"criteria row still has blocker_type: {row.get('requirement_id')}")

    phase_text = PHASE_DOC.read_text(encoding="utf-8")
    if "- status: blocked" in phase_text:
        failures.append("phase doc still contains a blocked criteria row")
    if "blocker_type: missing-" in phase_text or "blocker_type: stale-" in phase_text:
        failures.append("phase doc still contains a missing/stale blocker_type")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1

    print("validate_phase01_evidence: PASS")
    print("collected directories: 0")
    print(f"structured dossiers: {len(actual_dossiers)}")
    print("duplicate/copy/backup suffix matches: 0")
    print(f"retired legacy paths checked: {len(retired_paths)}")
    print("criteria rows satisfied: yes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
