#!/usr/bin/env python3
"""Validate Phase 02 promoted-file source/rationale coverage.

The validator treats every current ``core/**/*.md`` file as a promoted core
Markdown artifact unless the file carries direct source/rationale markers.
Coverage can be supplied either in-file or by the Phase 02 manifest.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


DEFAULT_MANIFEST = "core/P02_SOURCE_RATIONALE_MANIFEST.json"
SOURCE_RE = re.compile(r"(?im)^\s*(Sources?|Sources Considered)\s*[:|]")
RATIONALE_RE = re.compile(
    r"(?im)^\s*Rationale\s*[:|]|Rationale \(Recency/Completeness/Reuse\)"
)


def _repo_rel(path: Path, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def _has_direct_markers(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    return bool(SOURCE_RE.search(text) and RATIONALE_RE.search(text))


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ERROR: manifest JSON parse failed at {path}: {exc}")
    if not isinstance(data, dict):
        raise SystemExit(f"ERROR: manifest root must be an object: {path}")
    return data


def _validate_group_shape(group: Any, index: int) -> list[str]:
    issues: list[str] = []
    if not isinstance(group, dict):
        return [f"coverage_groups[{index}] is not an object"]
    group_id = group.get("id")
    if not isinstance(group_id, str) or not group_id.strip():
        issues.append(f"coverage_groups[{index}].id is required")
    sources = group.get("sources")
    if (
        not isinstance(sources, list)
        or not sources
        or not all(isinstance(item, str) and item.strip() for item in sources)
    ):
        issues.append(f"coverage_groups[{index}].sources must be non-empty strings")
    rationale = group.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        issues.append(f"coverage_groups[{index}].rationale is required")
    files = group.get("files")
    if (
        not isinstance(files, list)
        or not files
        or not all(isinstance(item, str) and item.strip() for item in files)
    ):
        issues.append(f"coverage_groups[{index}].files must be non-empty strings")
    return issues


def validate(repo_root: Path, manifest_path: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    core_root = repo_root / "core"
    manifest = _load_manifest(manifest_path)
    if manifest.get("schema_version") != "1.0":
        raise SystemExit("ERROR: manifest schema_version must be '1.0'")

    core_files = sorted(_repo_rel(path, repo_root) for path in core_root.rglob("*.md"))
    core_set = set(core_files)
    direct = [
        rel
        for rel in core_files
        if _has_direct_markers(repo_root / rel)
    ]

    invalid_groups: list[str] = []
    stale_manifest_files: list[str] = []
    duplicate_manifest_files: list[str] = []
    manifest_coverage: dict[str, str] = {}

    groups = manifest.get("coverage_groups")
    if not isinstance(groups, list):
        invalid_groups.append("coverage_groups must be a list")
        groups = []

    for index, group in enumerate(groups):
        shape_issues = _validate_group_shape(group, index)
        invalid_groups.extend(shape_issues)
        if shape_issues or not isinstance(group, dict):
            continue
        group_id = group["id"].strip()
        for raw_file in group["files"]:
            rel = raw_file.replace("\\", "/").strip()
            if rel.startswith("/") or ".." in Path(rel).parts:
                invalid_groups.append(f"{group_id}: invalid relative path {rel!r}")
                continue
            if not rel.startswith("core/") or not rel.endswith(".md"):
                invalid_groups.append(f"{group_id}: file must be core markdown: {rel}")
                continue
            if rel not in core_set:
                stale_manifest_files.append(rel)
                continue
            if rel in manifest_coverage:
                duplicate_manifest_files.append(rel)
                continue
            manifest_coverage[rel] = group_id

    covered = set(direct) | set(manifest_coverage)
    missing = sorted(core_set - covered)
    healthy = not (
        invalid_groups
        or stale_manifest_files
        or duplicate_manifest_files
        or missing
    )
    return {
        "healthy": healthy,
        "manifest": _repo_rel(manifest_path, repo_root),
        "totalCoreMarkdown": len(core_files),
        "directMarkerCoverage": len(direct),
        "manifestCoverage": len(manifest_coverage),
        "coveredMarkdown": len(covered),
        "missingCoverage": missing,
        "staleManifestFiles": sorted(stale_manifest_files),
        "duplicateManifestFiles": sorted(set(duplicate_manifest_files)),
        "invalidGroups": invalid_groups,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", default=".", help="Repository root.")
    parser.add_argument(
        "--manifest",
        default=DEFAULT_MANIFEST,
        help=f"Coverage manifest path, default: {DEFAULT_MANIFEST}",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON report.")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root)
    manifest_path = (repo_root / args.manifest).resolve()
    report = validate(repo_root, manifest_path)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            "P02 source/rationale coverage: "
            f"{report['coveredMarkdown']}/{report['totalCoreMarkdown']} covered"
        )
        if report["healthy"]:
            print("Status: HEALTHY")
        else:
            print("Status: ISSUES FOUND")
            for key in (
                "missingCoverage",
                "staleManifestFiles",
                "duplicateManifestFiles",
                "invalidGroups",
            ):
                values = report[key]
                if values:
                    print(f"{key}: {len(values)}")
                    for value in values:
                        print(f"  - {value}")

    return 0 if report["healthy"] else 1


if __name__ == "__main__":
    sys.exit(main())
