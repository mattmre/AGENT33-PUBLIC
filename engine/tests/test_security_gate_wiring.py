"""Tests verifying evaluate_security_gate() is called from the release workflow.

Gap 2 of BHS Gate 5.3 remediation: evaluate_security_gate() must be invoked
automatically when start_validation() is called on a release, using the most
recent completed security scan run.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from agent33.component_security.models import (
    RunStatus,
    ScanTarget,
    SecurityGatePolicy,
    SecurityProfile,
)
from agent33.release.models import (
    CheckStatus,
    ReleaseStatus,
    ReleaseType,
)
from agent33.release.service import ReleaseService
from agent33.services.security_scan import SecurityScanService

if TYPE_CHECKING:
    from pathlib import Path


def _fake_completed(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def _clean_command_runner(
    command: list[str], _timeout_seconds: int
) -> subprocess.CompletedProcess[str]:
    if "bandit" in " ".join(command):
        return _fake_completed('{"results": []}')
    if command and command[0] == "gitleaks":
        return _fake_completed("[]")
    if "pip_audit" in " ".join(command):
        return _fake_completed('{"dependencies": []}')
    if command and command[0] == "semgrep":
        return _fake_completed('{"results": []}')
    return _fake_completed("")


def _high_finding_runner(
    command: list[str], _timeout_seconds: int
) -> subprocess.CompletedProcess[str]:
    """Runner that returns one HIGH bandit finding."""
    import json

    if "bandit" in " ".join(command):
        return _fake_completed(
            json.dumps(
                {
                    "results": [
                        {
                            "issue_severity": "HIGH",
                            "issue_text": "Use of subprocess with shell=True",
                            "filename": "app.py",
                            "line_number": 1,
                            "issue_cwe": {"id": "78"},
                        }
                    ]
                }
            ),
            returncode=1,
        )
    if command and command[0] == "gitleaks":
        return _fake_completed("[]")
    return _fake_completed("")


class TestSecurityGateAutoEvaluation:
    async def test_start_validation_calls_evaluate_security_gate_with_clean_scan(
        self, tmp_path: Path
    ) -> None:
        """When a completed scan with zero findings exists, start_validation() sets
        RL-06 to PASS."""
        scan_service = SecurityScanService(command_runner=_clean_command_runner)

        # Create and complete a scan run
        scan_run = scan_service.create_run(
            target=ScanTarget(repository_path=str(tmp_path)),
            profile=SecurityProfile.QUICK,
        )
        completed = await scan_service.launch_scan(scan_run.id)
        assert completed.status == RunStatus.COMPLETED
        assert completed.findings_summary.total == 0

        release_service = ReleaseService(security_scan_service=scan_service)
        release = release_service.create_release(version="1.0.0", release_type=ReleaseType.MINOR)
        release_service.freeze(release.release_id)
        release_service.cut_rc(release.release_id)

        validated = release_service.start_validation(release.release_id)

        assert validated.status == ReleaseStatus.VALIDATING
        rl06 = next((c for c in validated.evidence.checklist if c.check_id == "RL-06"), None)
        assert rl06 is not None
        assert rl06.status == CheckStatus.PASS
        assert "passed" in rl06.message.lower()
        assert validated.evidence.gate_passed is True

    async def test_start_validation_sets_rl06_fail_when_high_findings_exceed_policy(
        self, tmp_path: Path
    ) -> None:
        """When a scan has HIGH findings that exceed policy, RL-06 is set to FAIL."""
        scan_service = SecurityScanService(command_runner=_high_finding_runner)

        scan_run = scan_service.create_run(
            target=ScanTarget(repository_path=str(tmp_path)),
            profile=SecurityProfile.QUICK,
        )
        completed = await scan_service.launch_scan(scan_run.id)
        assert completed.status == RunStatus.COMPLETED
        assert completed.findings_summary.high >= 1

        # Policy: block on any high finding
        policy = SecurityGatePolicy(block_on_critical=True, block_on_high=True, max_high=0)
        release_service = ReleaseService(
            security_scan_service=scan_service, security_gate_policy=policy
        )
        release = release_service.create_release(version="1.1.0")
        release_service.freeze(release.release_id)
        release_service.cut_rc(release.release_id)

        validated = release_service.start_validation(release.release_id)

        rl06 = next((c for c in validated.evidence.checklist if c.check_id == "RL-06"), None)
        assert rl06 is not None
        assert rl06.status == CheckStatus.FAIL
        assert "high findings" in rl06.message.lower()
        assert validated.evidence.gate_passed is False

    def test_start_validation_sets_rl06_fail_when_no_scan_available(self) -> None:
        """When no completed scan exists, start_validation() sets RL-06 to FAIL
        with an explanatory message rather than silently skipping the gate."""
        scan_service = SecurityScanService(command_runner=_clean_command_runner)
        # No scan run created — scan service is empty

        release_service = ReleaseService(security_scan_service=scan_service)
        release = release_service.create_release(version="2.0.0")
        release_service.freeze(release.release_id)
        release_service.cut_rc(release.release_id)

        validated = release_service.start_validation(release.release_id)

        rl06 = next((c for c in validated.evidence.checklist if c.check_id == "RL-06"), None)
        assert rl06 is not None
        assert rl06.status == CheckStatus.FAIL
        assert "no completed scan" in rl06.message.lower()
        assert validated.evidence.gate_passed is False

    def test_start_validation_skips_gate_when_no_scan_service_wired(self) -> None:
        """When no SecurityScanService is provided, RL-06 is not auto-evaluated
        (stays at its default status) and the release still transitions."""
        release_service = ReleaseService(security_scan_service=None)
        release = release_service.create_release(version="3.0.0")
        release_service.freeze(release.release_id)
        release_service.cut_rc(release.release_id)

        validated = release_service.start_validation(release.release_id)

        assert validated.status == ReleaseStatus.VALIDATING
        rl06 = next((c for c in validated.evidence.checklist if c.check_id == "RL-06"), None)
        assert rl06 is not None
        # RL-06 should still be at its default state (not auto-updated)
        assert rl06.status == CheckStatus.PENDING

    async def test_release_scoped_scan_is_preferred_over_most_recent(self, tmp_path: Path) -> None:
        """A scan run tagged with the release_id is preferred over a generic recent run."""
        scan_service = SecurityScanService(command_runner=_high_finding_runner)

        # Generic recent run with high findings
        generic_run = scan_service.create_run(
            target=ScanTarget(repository_path=str(tmp_path)),
            profile=SecurityProfile.QUICK,
        )
        await scan_service.launch_scan(generic_run.id)

        release_service = ReleaseService(security_scan_service=scan_service)
        release = release_service.create_release(version="4.0.0")
        release_service.freeze(release.release_id)
        release_service.cut_rc(release.release_id)

        # Release-scoped scan with NO findings (clean)
        release_scan_service = SecurityScanService(command_runner=_clean_command_runner)
        release_run = release_scan_service.create_run(
            target=ScanTarget(repository_path=str(tmp_path)),
            profile=SecurityProfile.QUICK,
            release_candidate_id=release.release_id,
        )
        await release_scan_service.launch_scan(release_run.id)

        # Inject both runs into the same service
        scan_service._runs[release_run.id] = release_scan_service._runs[release_run.id]
        scan_service._findings[release_run.id] = release_scan_service._findings.get(
            release_run.id, []
        )

        validated = release_service.start_validation(release.release_id)

        rl06 = next((c for c in validated.evidence.checklist if c.check_id == "RL-06"), None)
        assert rl06 is not None
        # The release-scoped clean run should win → PASS
        assert rl06.status == CheckStatus.PASS
