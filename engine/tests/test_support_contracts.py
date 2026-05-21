from __future__ import annotations

from agent33.support.bundles import (
    SupportBundleRequest,
    SupportBundleSection,
    build_support_bundle_manifest,
)
from agent33.support.diagnostics import (
    SetupDiagnosticCheck,
    SetupDiagnosticStatus,
    build_setup_diagnostic_report,
    summarize_setup_diagnostics,
)


def test_support_bundle_manifest_preserves_requested_sections() -> None:
    request = SupportBundleRequest(
        bundle_id="bundle-1",
        include_sections=[
            SupportBundleSection.DIAGNOSTICS,
            SupportBundleSection.LOGS,
        ],
    )

    manifest = build_support_bundle_manifest(request)

    assert manifest.bundle_id == "bundle-1"
    assert manifest.sections == [
        SupportBundleSection.DIAGNOSTICS,
        SupportBundleSection.LOGS,
    ]
    assert manifest.redacted is True
    assert manifest.files == ["diagnostics.json", "logs.json", "redaction-report.json"]


def test_setup_diagnostics_summary_counts_statuses() -> None:
    checks = [
        SetupDiagnosticCheck(
            check_id="docker",
            status=SetupDiagnosticStatus.PASS,
        ),
        SetupDiagnosticCheck(
            check_id="secrets",
            status=SetupDiagnosticStatus.FAIL,
            fix_action="set OPENAI_API_KEY",
        ),
    ]

    summary = summarize_setup_diagnostics(checks)

    assert summary[SetupDiagnosticStatus.PASS] == 1
    assert summary[SetupDiagnosticStatus.WARN] == 0
    assert summary[SetupDiagnosticStatus.FAIL] == 1


def test_setup_diagnostic_report_lists_required_actions_and_evidence() -> None:
    checks = [
        SetupDiagnosticCheck(
            check_id="docker",
            status=SetupDiagnosticStatus.WARN,
            fix_action="start Docker Desktop",
            evidence_uri="diagnostic://docker",
        ),
        SetupDiagnosticCheck(
            check_id="model",
            status=SetupDiagnosticStatus.PASS,
            evidence_uri="diagnostic://model",
        ),
    ]

    report = build_setup_diagnostic_report(checks)

    assert report.counts[SetupDiagnosticStatus.WARN] == 1
    assert report.required_actions == ["start Docker Desktop"]
    assert report.evidence_uris == ["diagnostic://docker", "diagnostic://model"]
