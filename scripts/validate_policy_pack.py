#!/usr/bin/env python3
"""Validate Phase 05 policy-pack and risk-trigger closeout evidence."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path


REQUIRED_PACK_FILES = (
    "AGENTS.md",
    "ORCHESTRATION.md",
    "EVIDENCE.md",
    "RISK_TRIGGERS.md",
    "ACCEPTANCE_CHECKS.md",
    "PROMOTION_GUIDE.md",
)

TRIGGER_FAMILIES = (
    "Prompt injection",
    "Sandbox escape",
    "Secrets/tokens",
    "Supply chain",
)

PROMOTION_TERMS = (
    "acceptance checks",
    "verification evidence",
    "security posture",
    "changelog",
)

STALE_PHASE5_PATHS = (
    "docs/session-logs/SESSION-2026-01-16_AGENT-33_PHASE-5.md",
    "docs\\session-logs\\SESSION-2026-01-16_AGENT-33_PHASE-5.md",
)

P05_EVIDENCE_GLOBS = (
    "docs/architecture/PHASE-05-POLICY-PACK-AND-RISK-TRIGGERS.md",
    "docs/architecture/reviews/phase-05*.md",
    "core/packs/policy-pack-v1/**/*.md",
)


@dataclass(frozen=True)
class Finding:
    code: str
    message: str


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _contains(text: str, needle: str) -> bool:
    return needle.casefold() in text.casefold()


def _expand_evidence_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for pattern in P05_EVIDENCE_GLOBS:
        matches = sorted(root.glob(pattern))
        paths.extend(path for path in matches if path.is_file())
    return sorted(set(paths))


def _validate_pack_inventory(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    pack_dir = root / "core" / "packs" / "policy-pack-v1"
    for filename in REQUIRED_PACK_FILES:
        path = pack_dir / filename
        if not path.is_file():
            findings.append(
                Finding("missing-pack-file", f"required pack file missing: {path}")
            )
    return findings


def _validate_trigger_drift(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    risk_path = root / "core" / "packs" / "policy-pack-v1" / "RISK_TRIGGERS.md"
    checklist_path = root / "core" / "orchestrator" / "handoff" / "REVIEW_CHECKLIST.md"
    if not risk_path.is_file():
        return [Finding("missing-risk-triggers", f"missing {risk_path}")]
    if not checklist_path.is_file():
        return [Finding("missing-review-checklist", f"missing {checklist_path}")]

    risk_text = _read_text(risk_path)
    checklist_text = _read_text(checklist_path)
    for family in TRIGGER_FAMILIES:
        if not _contains(risk_text, family):
            findings.append(
                Finding(
                    "risk-trigger-family-missing",
                    f"{family!r} missing from {risk_path}",
                )
            )
        if not _contains(checklist_text, family):
            findings.append(
                Finding(
                    "checklist-trigger-family-missing",
                    f"{family!r} missing from {checklist_path}",
                )
            )

    risk_ref = "core/packs/policy-pack-v1/RISK_TRIGGERS.md"
    if risk_ref not in checklist_text:
        findings.append(
            Finding(
                "checklist-risk-reference-missing",
                f"{risk_ref!r} missing from {checklist_path}",
            )
        )
    return findings


def _validate_promotion_traceability(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    paths = (
        root / "core" / "packs" / "policy-pack-v1" / "PROMOTION_GUIDE.md",
        root / "core" / "workflows" / "PROMOTION_CRITERIA.md",
    )
    for path in paths:
        if not path.is_file():
            findings.append(Finding("missing-promotion-file", f"missing {path}"))
            continue
        text = _read_text(path)
        for term in PROMOTION_TERMS:
            if not _contains(text, term):
                findings.append(
                    Finding(
                        "promotion-term-missing",
                        f"{term!r} missing from {path}",
                    )
                )
    return findings


def _validate_changelog_closeout(root: Path) -> list[Finding]:
    changelog_path = root / "core" / "CHANGELOG.md"
    if not changelog_path.is_file():
        return [Finding("missing-changelog", f"missing {changelog_path}")]
    text = _read_text(changelog_path)
    required_terms = (
        "2026-05-24",
        "core/packs/policy-pack-v1",
        "policy-pack v1",
        "closeout",
    )
    missing = [term for term in required_terms if not _contains(text, term)]
    if missing:
        return [
            Finding(
                "missing-policy-pack-closeout-changelog",
                f"{changelog_path} missing explicit policy-pack v1 closeout terms: {', '.join(missing)}",
            )
        ]
    return []


def _validate_closeout_replacement(root: Path) -> list[Finding]:
    closeouts = sorted(root.glob("docs/architecture/reviews/phase-05-*-closeout-2026-05-24.md"))
    if not closeouts:
        return [
            Finding(
                "missing-p05-closeout",
                "missing docs/architecture/reviews/phase-05-*-closeout-2026-05-24.md",
            )
        ]

    text = "\n".join(_read_text(path) for path in closeouts)
    required_terms = (
        "BHS score: 100",
        "BHS delta: 92 -> 100",
        "Ledger replacement: accepted",
        "Residual blockers: none",
    )
    missing = [term for term in required_terms if not _contains(text, term)]
    if missing:
        return [
            Finding(
                "incomplete-p05-closeout",
                f"P05 closeout missing required replacement terms: {', '.join(missing)}",
            )
        ]
    return []


def _validate_stale_p05_evidence_paths(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in _expand_evidence_paths(root):
        text = _read_text(path)
        for stale_path in STALE_PHASE5_PATHS:
            if stale_path in text:
                findings.append(
                    Finding(
                        "stale-p05-evidence-path",
                        f"stale Phase 5 session-log path remains in {path}: {stale_path}",
                    )
                )
    return findings


def validate_repo(root: Path) -> list[Finding]:
    checks = (
        _validate_pack_inventory,
        _validate_trigger_drift,
        _validate_promotion_traceability,
        _validate_changelog_closeout,
        _validate_closeout_replacement,
        _validate_stale_p05_evidence_paths,
    )
    findings: list[Finding] = []
    for check in checks:
        findings.extend(check(root))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate Phase 05 policy-pack/risk-trigger closeout evidence."
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root. Defaults to current working directory.",
    )
    args = parser.parse_args(argv)

    root = Path(args.repo_root).resolve()
    findings = validate_repo(root)
    if findings:
        for finding in findings:
            print(f"ERROR[{finding.code}]: {finding.message}", file=sys.stderr)
        return 1

    print("validate_policy_pack: PASS")
    print(f"required_pack_files={len(REQUIRED_PACK_FILES)}")
    print(f"risk_trigger_families={len(TRIGGER_FAMILIES)}")
    print("changelog_closeout=present")
    print("ledger_replacement_closeout=accepted")
    print("stale_p05_evidence_paths=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
