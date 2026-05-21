"""Pre-release checklist validation (RL-01..RL-08).

Implements the pre-release checklist from ``core/orchestrator/RELEASE_CADENCE.md``.
"""

from __future__ import annotations

import logging

from agent33.release.models import (
    CheckStatus,
    Release,
    ReleaseCheck,
    ReleaseType,
)

logger = logging.getLogger(__name__)


# The canonical pre-release checks
_CHECKS: list[tuple[str, str, bool]] = [
    ("RL-01", "All PRs merged", True),
    ("RL-02", "Gates pass", True),
    ("RL-03", "Changelog updated", True),
    ("RL-04", "Version bumped", True),
    ("RL-05", "Documentation updated", True),
    ("RL-06", "Security review", True),
    ("RL-07", "Rollback tested", True),  # Required for Major only
    ("RL-08", "Release notes drafted", True),
]


def build_checklist(release: Release) -> list[ReleaseCheck]:
    """Build the pre-release checklist for a release.

    RL-07 (Rollback tested) is only required for major releases.
    """
    checks: list[ReleaseCheck] = []
    for check_id, name, required in _CHECKS:
        # RL-07 is only required for major releases
        actual_required = required
        if check_id == "RL-07" and release.release_type != ReleaseType.MAJOR:
            actual_required = False
        checks.append(
            ReleaseCheck(
                check_id=check_id,
                name=name,
                required=actual_required,
            )
        )
    return checks


class ChecklistEvaluator:
    """Evaluate a release checklist and determine readiness."""

    def evaluate(self, checks: list[ReleaseCheck]) -> tuple[bool, list[str]]:
        """Evaluate checklist.

        Returns (all_passed, list of failure descriptions).
        """
        failures: list[str] = []
        for check in checks:
            if not check.required:
                continue
            if check.status not in (CheckStatus.PASS, CheckStatus.NA):
                failures.append(f"{check.check_id} ({check.name}): {check.status.value}")
        return len(failures) == 0, failures

    def update_check(
        self,
        checks: list[ReleaseCheck],
        check_id: str,
        status: CheckStatus,
        message: str = "",
    ) -> ReleaseCheck | None:
        """Update a specific check's status."""
        for check in checks:
            if check.check_id == check_id:
                check.status = status
                if message:
                    check.message = message
                return check
        return None
