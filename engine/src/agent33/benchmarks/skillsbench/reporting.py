"""CTRF export helpers for SkillsBench benchmark runs."""

from __future__ import annotations

from typing import Any

from agent33.benchmarks.skillsbench.models import BenchmarkRunResult, TrialOutcome
from agent33.benchmarks.skillsbench.regression import attach_baseline_comparison


class SkillsBenchCTRFGenerator:
    """Generate CTRF-style reports for benchmark runs."""

    TOOL_NAME = "agent33-skillsbench"
    TOOL_VERSION = "1.0.0"

    def generate_report(
        self,
        run: BenchmarkRunResult,
        baseline_report: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate a CTRF-compatible JSON structure for a benchmark run."""
        tests: list[dict[str, Any]] = []
        passed = 0
        failed = 0
        skipped = 0

        for trial in run.trials:
            if trial.outcome == TrialOutcome.PASSED:
                status = "passed"
            elif trial.outcome == TrialOutcome.SKIPPED:
                status = "skipped"
            else:
                status = "failed"
            if status == "passed":
                passed += 1
            elif status == "skipped":
                skipped += 1
            else:
                failed += 1
            tests.append(
                {
                    "name": (
                        f"{trial.task_id} [trial {trial.trial_number}]"
                        f" [{trial.agent}/{trial.model}]"
                    ),
                    "status": status,
                    "duration": trial.duration_ms,
                    "message": trial.error_message or trial.termination_reason,
                    "extra": {
                        "skills_enabled": trial.skills_enabled,
                        "iterations": trial.iterations,
                        "tool_calls_made": trial.tool_calls_made,
                        "tokens_used": trial.tokens_used,
                        "pytest_returncode": trial.pytest_returncode,
                        "artifacts": [artifact.model_dump() for artifact in trial.artifacts],
                        "skillsbench": {
                            "trial_outcome": trial.outcome,
                            "task_id": trial.task_id,
                            "category": (
                                trial.task_id.split("/", 1)[0] if "/" in trial.task_id else ""
                            ),
                        },
                    },
                }
            )

        start_ms = int(run.started_at.timestamp() * 1000)
        stop_ms = int(run.completed_at.timestamp() * 1000) if run.completed_at else start_ms

        report = {
            "results": {
                "tool": {
                    "name": self.TOOL_NAME,
                    "version": self.TOOL_VERSION,
                },
                "summary": {
                    "tests": len(tests),
                    "passed": passed,
                    "failed": failed,
                    "skipped": skipped,
                    "pending": 0,
                    "other": 0,
                    "start": start_ms,
                    "stop": stop_ms,
                },
                "extra": {
                    "skillsbench": {
                        "run_id": run.run_id,
                        "total_tasks": run.total_tasks,
                        "total_trials": run.total_trials,
                        "pass_rate": run.pass_rate,
                        "task_summaries": [
                            summary.model_dump(mode="json") for summary in run.task_summaries
                        ],
                    },
                },
                "tests": tests,
            },
        }
        if baseline_report is not None:
            attach_baseline_comparison(report, baseline_report)
        return report
