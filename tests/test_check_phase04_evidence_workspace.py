from __future__ import annotations

from scripts.check_phase04_evidence_workspace import classify_paths, classify_repo_path


def test_phase04_owned_paths_are_accepted() -> None:
    assert (
        classify_repo_path("engine/src/agent33/testing/agent_harness.py")
        == "phase04-owned"
    )
    assert (
        classify_repo_path(
            "docs/architecture/reviews/phase-04-agent-harness-closeout-2026-05-24.md"
        )
        == "phase04-owned"
    )


def test_known_generated_paths_are_policy_ignored() -> None:
    assert classify_repo_path(".coverage") == "known-generated-policy-ignored"
    assert (
        classify_repo_path("engine/test-results/ctrf-smoke-report.json")
        == "known-generated-policy-ignored"
    )
    assert (
        classify_repo_path(".audit/00-CERTIFICATION-SHEET.md")
        == "known-generated-policy-ignored"
    )
    assert (
        classify_repo_path("var/improvement_learning_signals.sqlite3")
        == "known-generated-policy-ignored"
    )


def test_unexpected_path_fails_closed() -> None:
    classified = classify_paths(["README.md"])

    assert classified[0].path == "README.md"
    assert classified[0].classification == "unexpected"
