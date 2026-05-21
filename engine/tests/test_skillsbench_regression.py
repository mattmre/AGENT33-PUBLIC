"""Regression tests for SkillsBench baseline comparison helpers."""

from __future__ import annotations

from agent33.benchmarks.skillsbench.regression import (
    SkillsBenchRegressionThresholds,
    attach_baseline_comparison,
    compare_ctrf_reports,
)


def _make_report(task_summaries: list[dict[str, object]]) -> dict[str, object]:
    total = sum(int(summary["total_trials"]) for summary in task_summaries)
    passed = sum(int(summary["passed_trials"]) for summary in task_summaries)
    failed = sum(
        int(summary["failed_trials"]) + int(summary.get("error_trials", 0))
        for summary in task_summaries
    )
    skipped = sum(int(summary.get("skipped_trials", 0)) for summary in task_summaries)
    return {
        "results": {
            "summary": {
                "tests": total,
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "pending": 0,
                "other": 0,
                "start": 1,
                "stop": 2,
            },
            "extra": {
                "skillsbench": {
                    "task_summaries": task_summaries,
                }
            },
            "tests": [],
        }
    }


def test_compare_ctrf_reports_detects_task_and_category_regressions() -> None:
    baseline = _make_report(
        [
            {
                "task_id": "alpha/one",
                "category": "alpha",
                "total_trials": 1,
                "passed_trials": 1,
                "failed_trials": 0,
                "error_trials": 0,
                "pass_rate": 1.0,
            },
            {
                "task_id": "beta/two",
                "category": "beta",
                "total_trials": 1,
                "passed_trials": 1,
                "failed_trials": 0,
                "error_trials": 0,
                "pass_rate": 1.0,
            },
        ]
    )
    current = _make_report(
        [
            {
                "task_id": "alpha/one",
                "category": "alpha",
                "total_trials": 1,
                "passed_trials": 0,
                "failed_trials": 1,
                "error_trials": 0,
                "pass_rate": 0.0,
            },
            {
                "task_id": "beta/two",
                "category": "beta",
                "total_trials": 1,
                "passed_trials": 1,
                "failed_trials": 0,
                "error_trials": 0,
                "pass_rate": 1.0,
            },
        ]
    )

    comparison = compare_ctrf_reports(current, baseline)

    assert comparison.has_regressions is True
    assert comparison.overall.regressed is True
    assert comparison.overall.drop_pp == 50.0
    assert [entry.id for entry in comparison.task_regressions] == ["alpha/one"]
    assert [entry.id for entry in comparison.category_regressions] == ["alpha"]


def test_compare_ctrf_reports_ignores_subthreshold_task_changes() -> None:
    baseline = _make_report(
        [
            {
                "task_id": "alpha/one",
                "category": "alpha",
                "total_trials": 6,
                "passed_trials": 6,
                "failed_trials": 0,
                "error_trials": 0,
                "pass_rate": 1.0,
            }
        ]
    )
    current = _make_report(
        [
            {
                "task_id": "alpha/one",
                "category": "alpha",
                "total_trials": 6,
                "passed_trials": 5,
                "failed_trials": 1,
                "error_trials": 0,
                "pass_rate": 5 / 6,
            }
        ]
    )

    comparison = compare_ctrf_reports(
        current,
        baseline,
        thresholds=SkillsBenchRegressionThresholds(
            overall_pass_rate_drop_pp=20.0,
            task_pass_rate_drop_pp=20.0,
            category_pass_rate_drop_pp=20.0,
        ),
    )

    assert comparison.has_regressions is False
    assert comparison.task_regressions == []
    assert comparison.category_regressions == []


def test_attach_baseline_comparison_persists_extra_metadata() -> None:
    baseline = _make_report(
        [
            {
                "task_id": "smoke/test-a",
                "category": "smoke",
                "total_trials": 1,
                "passed_trials": 1,
                "failed_trials": 0,
                "error_trials": 0,
                "pass_rate": 1.0,
            }
        ]
    )
    current = _make_report(
        [
            {
                "task_id": "smoke/test-a",
                "category": "smoke",
                "total_trials": 1,
                "passed_trials": 0,
                "failed_trials": 1,
                "error_trials": 0,
                "pass_rate": 0.0,
            }
        ]
    )

    comparison = attach_baseline_comparison(current, baseline)

    extra = current["results"]["extra"]["skillsbench"]
    assert comparison.has_regressions is True
    assert extra["baseline_comparison"]["task_regressions"][0]["id"] == "smoke/test-a"
