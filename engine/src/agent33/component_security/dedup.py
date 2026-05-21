"""Finding deduplication utilities for component security scans."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent33.component_security.models import SecurityFinding


def compute_finding_fingerprint(finding: SecurityFinding) -> str:
    """Compute a SHA-256 fingerprint from the finding's identity fields.

    Identity is defined as: ``tool + file_path + line_number + category + cwe_id``.
    """
    parts = [
        finding.tool,
        finding.file_path,
        str(finding.line_number or ""),
        finding.category.value,
        finding.cwe_id,
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()


def deduplicate_findings(findings: list[SecurityFinding]) -> list[SecurityFinding]:
    """Return unique findings by fingerprint, keeping first occurrence."""
    seen: set[str] = set()
    unique: list[SecurityFinding] = []
    for finding in findings:
        fp = compute_finding_fingerprint(finding)
        if fp in seen:
            continue
        seen.add(fp)
        unique.append(finding)
    return unique
