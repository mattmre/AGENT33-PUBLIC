"""Regression tests for SkillsBench storage and CTRF reporting."""

from __future__ import annotations

import pytest

from agent33.benchmarks.skillsbench.models import (
    BenchmarkRunResult,
    TrialOutcome,
    TrialRecord,
)
from agent33.benchmarks.skillsbench.reporting import SkillsBenchCTRFGenerator
from agent33.benchmarks.skillsbench.storage import SkillsBenchArtifactStore


def test_storage_rejects_invalid_run_id(tmp_path) -> None:
    store = SkillsBenchArtifactStore(tmp_path / "store")

    with pytest.raises(ValueError, match="Invalid SkillsBench run_id"):
        store.persist_run(BenchmarkRunResult(run_id="../escape"))


def test_list_runs_returns_summary_without_trials(tmp_path) -> None:
    store = SkillsBenchArtifactStore(tmp_path / "store")
    run = BenchmarkRunResult(
        run_id="sb-summary",
        total_tasks=1,
        total_trials=1,
        passed_trials=1,
        pass_rate=1.0,
        trials=[
            TrialRecord(
                task_id="math/addition",
                trial_number=1,
                outcome=TrialOutcome.PASSED,
            )
        ],
    )
    store.persist_run(run)

    summaries = store.list_runs(limit=1)

    assert len(summaries) == 1
    assert summaries[0].run_id == "sb-summary"
    assert summaries[0].total_trials == 1
    assert summaries[0].trials == []


def test_ctrf_generator_marks_skipped_trials() -> None:
    run = BenchmarkRunResult(
        run_id="sb-report",
        trials=[
            TrialRecord(task_id="math/addition", trial_number=1, outcome=TrialOutcome.PASSED),
            TrialRecord(task_id="math/subtract", trial_number=1, outcome=TrialOutcome.SKIPPED),
            TrialRecord(task_id="math/divide", trial_number=1, outcome=TrialOutcome.ERROR),
        ],
    )
    run.compute_aggregates()

    report = SkillsBenchCTRFGenerator().generate_report(run)

    assert [test["status"] for test in report["results"]["tests"]] == [
        "passed",
        "skipped",
        "failed",
    ]
    assert report["results"]["summary"]["passed"] == 1
    assert report["results"]["summary"]["skipped"] == 1
    assert report["results"]["summary"]["failed"] == 1
    assert (
        report["results"]["extra"]["skillsbench"]["task_summaries"][0]["task_id"]
        == "math/addition"
    )


def test_ctrf_generator_embeds_baseline_comparison() -> None:
    baseline_run = BenchmarkRunResult(
        run_id="sb-baseline",
        trials=[TrialRecord(task_id="math/addition", trial_number=1, outcome=TrialOutcome.PASSED)],
    )
    baseline_run.compute_aggregates()
    baseline_report = SkillsBenchCTRFGenerator().generate_report(baseline_run)

    current_run = BenchmarkRunResult(
        run_id="sb-current",
        trials=[TrialRecord(task_id="math/addition", trial_number=1, outcome=TrialOutcome.FAILED)],
    )
    current_run.compute_aggregates()

    report = SkillsBenchCTRFGenerator().generate_report(
        current_run, baseline_report=baseline_report
    )

    comparison = report["results"]["extra"]["skillsbench"]["baseline_comparison"]
    assert comparison["overall"]["regressed"] is True
    assert comparison["task_regressions"][0]["id"] == "math/addition"
