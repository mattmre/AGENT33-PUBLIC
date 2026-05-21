#!/usr/bin/env python3
"""Fail when a Trivy image report still contains blocked CVE IDs."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(
            "usage: verify_trivy_image.py <trivy-json-path> <cve-id> [<cve-id> ...]",
            file=sys.stderr,
        )
        return 2

    report_path = Path(argv[1])
    blocked_ids = set(argv[2:])
    report = json.loads(report_path.read_text(encoding="utf-8"))

    matches: list[tuple[str, str, str, str]] = []
    for result in report.get("Results", []):
        target = str(result.get("Target", "unknown"))
        for vulnerability in result.get("Vulnerabilities") or []:
            vulnerability_id = str(vulnerability.get("VulnerabilityID", ""))
            if vulnerability_id not in blocked_ids:
                continue
            matches.append(
                (
                    vulnerability_id,
                    target,
                    str(vulnerability.get("PkgName", "")),
                    str(vulnerability.get("InstalledVersion", "")),
                )
            )

    if not matches:
        print(f"No blocked CVEs found in {report_path.name}: {', '.join(sorted(blocked_ids))}")
        return 0

    print(f"Blocked CVEs still present in {report_path.name}:", file=sys.stderr)
    for vulnerability_id, target, package, installed_version in matches:
        print(
            f"- {vulnerability_id} target={target} package={package} installed={installed_version}",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
