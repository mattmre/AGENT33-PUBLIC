"""CTRF (Common Test Report Format) report generator.

Produces CTRF-compliant JSON reports from evaluation runs, gate results,
golden tasks, and multi-trial experiment runs.

See https://ctrf.io/ for the specification.
"""

from __future__ import annotations

import json
import logging
import time
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agent33.evaluation.multi_trial import MultiTrialRun

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CTRF models
# ---------------------------------------------------------------------------


class CTRFTestState(StrEnum):
    """Standard CTRF test states."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    PENDING = "pending"
    OTHER = "other"


class CTRFTest(BaseModel):
    """A single test entry in a CTRF report."""

    name: str
    status: CTRFTestState
    duration: float  # milliseconds
    message: str = ""
    trace: str = ""
    suite: str = ""
    type: str = ""  # e.g. "evaluation", "golden-task", "regression"
    filePath: str = ""  # noqa: N815
    retries: int = 0
    flaky: bool = False
    tags: list[str] = Field(default_factory=list)


class CTRFToolInfo(BaseModel):
    """Tool metadata for a CTRF report."""

    name: str = "agent33"
    version: str = ""


class CTRFSummary(BaseModel):
    """Aggregate counts for a CTRF report."""

    tests: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    pending: int = 0
    other: int = 0
    start: int = 0  # epoch milliseconds
    stop: int = 0  # epoch milliseconds


class CTRFEnvironment(BaseModel):
    """Optional environment metadata for a CTRF report."""

    reportName: str = ""  # noqa: N815
    buildName: str = ""  # noqa: N815
    buildUrl: str = ""  # noqa: N815
    extra: dict[str, Any] = Field(default_factory=dict)


class CTRFResults(BaseModel):
    """The results payload of a CTRF report."""

    tool: CTRFToolInfo
    summary: CTRFSummary
    tests: list[CTRFTest] = Field(default_factory=list)
    environment: CTRFEnvironment | None = None


class CTRFReport(BaseModel):
    """Top-level CTRF report container."""

    results: CTRFResults


# ---------------------------------------------------------------------------
# Backward-compatible legacy generator (used by multi-trial pipeline)
# ---------------------------------------------------------------------------


class CTRFGenerator:
    """Generates CTRF-compliant test result reports from MultiTrialRun data.

    This is the original dict-based generator retained for backward
    compatibility with the multi-trial pipeline.  New callers should prefer
    :class:`CTRFReportGenerator` which produces typed Pydantic models and
    supports evaluation runs, gate results, and golden tasks.
    """

    TOOL_NAME = "agent33-eval"
    TOOL_VERSION = "1.0.0"

    def __init__(self, pass_threshold: float = 0.6) -> None:
        self._pass_threshold = pass_threshold

    def generate_report(self, run: MultiTrialRun) -> dict[str, Any]:
        """Generate a full CTRF report from a MultiTrialRun."""
        tests: list[dict[str, Any]] = []
        total_passed = 0
        total_failed = 0
        total_skipped = 0

        for result in run.results:
            status = "passed" if result.pass_rate >= self._pass_threshold else "failed"
            if status == "passed":
                total_passed += 1
            else:
                total_failed += 1

            skills_label = " +skills" if result.skills_enabled else " -skills"
            tests.append(
                {
                    "name": (f"{result.task_id} [{result.agent}/{result.model}]" + skills_label),
                    "status": status,
                    "duration": result.total_duration_ms,
                    "extra": {
                        "trials": len(result.trials),
                        "pass_rate": result.pass_rate,
                        "variance": result.variance,
                        "skills_enabled": result.skills_enabled,
                        "agent": result.agent,
                        "model": result.model,
                        "tokens_used": result.total_tokens,
                        "trial_results": [t.score for t in result.trials],
                        "skillsbench": {
                            "mode": ("with_skills" if result.skills_enabled else "without_skills"),
                            "std_dev": result.std_dev,
                        },
                    },
                }
            )

        start_ms = int(run.started_at.timestamp() * 1000)
        stop_ms = int(run.completed_at.timestamp() * 1000) if run.completed_at else start_ms

        return {
            "results": {
                "tool": {
                    "name": self.TOOL_NAME,
                    "version": self.TOOL_VERSION,
                },
                "summary": {
                    "tests": len(tests),
                    "passed": total_passed,
                    "failed": total_failed,
                    "skipped": total_skipped,
                    "pending": 0,
                    "other": 0,
                    "start": start_ms,
                    "stop": stop_ms,
                },
                "extra": {
                    "skillsbench": {
                        "trials_per_combination": run.config.trials_per_combination,
                        "skills_modes": run.config.skills_modes,
                        "timeout_per_trial_seconds": run.config.timeout_per_trial_seconds,
                        "parallel_trials": run.config.parallel_trials,
                        "skills_impacts_count": len(run.skills_impacts),
                    },
                },
                "tests": tests,
            },
        }

    def generate_summary(self, run: MultiTrialRun) -> dict[str, Any]:
        """Generate summary statistics for a run."""
        if not run.results:
            return {"total_combinations": 0, "avg_pass_rate": 0.0}
        avg_pass = sum(r.pass_rate for r in run.results) / len(run.results)
        avg_var = sum(r.variance for r in run.results) / len(run.results)
        return {
            "total_combinations": len(run.results),
            "avg_pass_rate": round(avg_pass, 4),
            "avg_variance": round(avg_var, 4),
            "consistency": round(1 - avg_var, 4),
            "skills_impacts_count": len(run.skills_impacts),
        }

    def write_report(self, run: MultiTrialRun, path: Path) -> None:
        """Write CTRF JSON report to disk."""
        report = self.generate_report(run)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2))
        logger.info("ctrf_report_written path=%s", path)


# ---------------------------------------------------------------------------
# New typed CTRF report generator
# ---------------------------------------------------------------------------


class CTRFReportGenerator:
    """Generates typed CTRF reports from AGENT-33 evaluation subsystem data.

    Supports three conversion paths:
    - ``from_evaluation_run`` -- standard evaluation run results
    - ``from_gate_results`` -- regression gate check results
    - ``from_golden_tasks`` -- golden task execution results
    """

    def __init__(
        self,
        tool_name: str = "agent33",
        tool_version: str = "",
    ) -> None:
        self._tool = CTRFToolInfo(name=tool_name, version=tool_version)

    # ------------------------------------------------------------------
    # From evaluation run results
    # ------------------------------------------------------------------

    def from_evaluation_run(
        self,
        run_results: list[dict[str, Any]],
        start_time: int,
        end_time: int,
    ) -> CTRFReport:
        """Convert evaluation run results to a CTRF report.

        Parameters
        ----------
        run_results:
            List of dicts, each with at least ``item_id``, ``result``,
            and ``duration_ms`` keys (matching ``TaskRunResult.model_dump()``).
        start_time:
            Epoch milliseconds for the run start.
        end_time:
            Epoch milliseconds for the run end.
        """
        tests: list[CTRFTest] = []
        counts: dict[CTRFTestState, int] = {s: 0 for s in CTRFTestState}

        for item in run_results:
            state = _map_task_result(item.get("result", "fail"))
            counts[state] += 1
            tests.append(
                CTRFTest(
                    name=item.get("item_id", "unknown"),
                    status=state,
                    duration=float(item.get("duration_ms", 0)),
                    message=item.get("notes", ""),
                    suite="evaluation",
                    type="evaluation",
                    tags=_extract_tags(item),
                )
            )

        summary = CTRFSummary(
            tests=len(tests),
            passed=counts[CTRFTestState.PASSED],
            failed=counts[CTRFTestState.FAILED],
            skipped=counts[CTRFTestState.SKIPPED],
            pending=counts[CTRFTestState.PENDING],
            other=counts[CTRFTestState.OTHER],
            start=start_time,
            stop=end_time,
        )

        return CTRFReport(
            results=CTRFResults(tool=self._tool, summary=summary, tests=tests),
        )

    # ------------------------------------------------------------------
    # From gate results
    # ------------------------------------------------------------------

    def from_gate_results(
        self,
        gate_results: list[dict[str, Any]],
        start_time: int,
        end_time: int,
    ) -> CTRFReport:
        """Convert regression gate check results to a CTRF report.

        Parameters
        ----------
        gate_results:
            List of dicts, each with ``threshold`` (containing
            ``metric_id``, ``gate``, ``value``), ``actual_value``,
            and ``passed`` keys (matching ``GateCheckResult.model_dump()``).
        start_time:
            Epoch milliseconds for the gate check start.
        end_time:
            Epoch milliseconds for the gate check end.
        """
        tests: list[CTRFTest] = []
        counts: dict[CTRFTestState, int] = {s: 0 for s in CTRFTestState}

        for item in gate_results:
            passed = item.get("passed", False)
            state = CTRFTestState.PASSED if passed else CTRFTestState.FAILED
            counts[state] += 1

            threshold = item.get("threshold", {})
            metric_id = threshold.get("metric_id", "unknown")
            gate = threshold.get("gate", "unknown")
            threshold_value = threshold.get("value", 0)
            actual_value = item.get("actual_value", 0)

            tests.append(
                CTRFTest(
                    name=f"{gate}/{metric_id}",
                    status=state,
                    duration=0.0,
                    message=(
                        f"actual={actual_value} threshold={threshold_value}" if not passed else ""
                    ),
                    suite="regression-gate",
                    type="regression",
                    tags=[gate, metric_id],
                )
            )

        summary = CTRFSummary(
            tests=len(tests),
            passed=counts[CTRFTestState.PASSED],
            failed=counts[CTRFTestState.FAILED],
            skipped=counts[CTRFTestState.SKIPPED],
            pending=counts[CTRFTestState.PENDING],
            other=counts[CTRFTestState.OTHER],
            start=start_time,
            stop=end_time,
        )

        return CTRFReport(
            results=CTRFResults(tool=self._tool, summary=summary, tests=tests),
        )

    # ------------------------------------------------------------------
    # From golden task results
    # ------------------------------------------------------------------

    def from_golden_tasks(
        self,
        task_results: list[dict[str, Any]],
        start_time: int,
        end_time: int,
    ) -> CTRFReport:
        """Convert golden task execution results to a CTRF report.

        Parameters
        ----------
        task_results:
            List of dicts, each with ``item_id``, ``result``,
            ``duration_ms``, ``checks_passed``, ``checks_total``
            keys (matching ``TaskRunResult.model_dump()``).
        start_time:
            Epoch milliseconds for the run start.
        end_time:
            Epoch milliseconds for the run end.
        """
        tests: list[CTRFTest] = []
        counts: dict[CTRFTestState, int] = {s: 0 for s in CTRFTestState}

        for item in task_results:
            state = _map_task_result(item.get("result", "fail"))
            counts[state] += 1

            checks_passed = item.get("checks_passed", 0)
            checks_total = item.get("checks_total", 0)
            message = (
                f"checks: {checks_passed}/{checks_total}"
                if checks_total > 0
                else item.get("notes", "")
            )

            tests.append(
                CTRFTest(
                    name=item.get("item_id", "unknown"),
                    status=state,
                    duration=float(item.get("duration_ms", 0)),
                    message=message,
                    suite="golden-tasks",
                    type="golden-task",
                    tags=_extract_tags(item),
                )
            )

        summary = CTRFSummary(
            tests=len(tests),
            passed=counts[CTRFTestState.PASSED],
            failed=counts[CTRFTestState.FAILED],
            skipped=counts[CTRFTestState.SKIPPED],
            pending=counts[CTRFTestState.PENDING],
            other=counts[CTRFTestState.OTHER],
            start=start_time,
            stop=end_time,
        )

        return CTRFReport(
            results=CTRFResults(tool=self._tool, summary=summary, tests=tests),
        )

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    @staticmethod
    def to_json(report: CTRFReport) -> str:
        """Serialize a CTRF report to a JSON string."""
        return report.model_dump_json(indent=2)

    @staticmethod
    def to_file(report: CTRFReport, path: Path) -> None:
        """Write a CTRF report to a JSON file on disk."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report.model_dump_json(indent=2))
        logger.info("ctrf_report_written path=%s", path)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RESULT_STATE_MAP: dict[str, CTRFTestState] = {
    "pass": CTRFTestState.PASSED,
    "fail": CTRFTestState.FAILED,
    "skip": CTRFTestState.SKIPPED,
    "error": CTRFTestState.FAILED,
}


def _map_task_result(result: str) -> CTRFTestState:
    """Map an AGENT-33 TaskResult string to a CTRF test state."""
    return _RESULT_STATE_MAP.get(result, CTRFTestState.OTHER)


def _extract_tags(item: dict[str, Any]) -> list[str]:
    """Extract tags from a result dict if present."""
    tags = item.get("tags", [])
    if isinstance(tags, list):
        return [str(t) for t in tags]
    return []


def _now_ms() -> int:
    """Return the current time as epoch milliseconds."""
    return int(time.time() * 1000)
