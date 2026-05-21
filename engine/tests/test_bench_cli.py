"""CLI tests for benchmark regression reporting."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from agent33.cli.main import app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def _write_report(path: Path, task_summaries: list[dict[str, object]]) -> None:
    total = sum(int(summary["total_trials"]) for summary in task_summaries)
    passed = sum(int(summary["passed_trials"]) for summary in task_summaries)
    failed = sum(
        int(summary["failed_trials"]) + int(summary.get("error_trials", 0))
        for summary in task_summaries
    )
    payload = {
        "results": {
            "summary": {
                "tests": total,
                "passed": passed,
                "failed": failed,
                "skipped": 0,
                "pending": 0,
                "other": 0,
                "start": 1,
                "stop": 2,
            },
            "extra": {"skillsbench": {"task_summaries": task_summaries}},
            "tests": [],
        }
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_bench_report_writes_github_step_summary(tmp_path: Path) -> None:
    current = tmp_path / "current.json"
    baseline = tmp_path / "baseline.json"
    summary = tmp_path / "summary.md"
    _write_report(
        baseline,
        [
            {
                "task_id": "alpha/one",
                "category": "alpha",
                "total_trials": 1,
                "passed_trials": 1,
                "failed_trials": 0,
                "error_trials": 0,
                "pass_rate": 1.0,
            }
        ],
    )
    _write_report(
        current,
        [
            {
                "task_id": "alpha/one",
                "category": "alpha",
                "total_trials": 1,
                "passed_trials": 0,
                "failed_trials": 1,
                "error_trials": 0,
                "pass_rate": 0.0,
            }
        ],
    )

    result = runner.invoke(
        app,
        [
            "bench",
            "report",
            str(current),
            "--baseline",
            str(baseline),
            "--github-step-summary",
        ],
        env={"GITHUB_STEP_SUMMARY": str(summary)},
    )

    assert result.exit_code == 0
    assert "[REGRESSION]" in result.output
    assert "Task regressions" in summary.read_text(encoding="utf-8")


def test_bench_report_accepts_stdin() -> None:
    payload = {
        "results": {
            "summary": {
                "tests": 1,
                "passed": 1,
                "failed": 0,
                "skipped": 0,
                "pending": 0,
                "other": 0,
                "start": 1,
                "stop": 2,
            },
            "tests": [],
        }
    }

    result = runner.invoke(app, ["bench", "report", "-"], input=json.dumps(payload))

    assert result.exit_code == 0
    assert "SkillsBench Report: stdin" in result.output
