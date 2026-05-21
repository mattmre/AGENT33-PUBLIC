"""SkillsBench 86-task benchmark harness.

Provides models, configuration, and execution logic for running SkillsBench-style
benchmark evaluations.  Each task is run N times (default 5) with binary reward
(all-or-nothing) scoring, and skills impact is computed as the delta between
pass rates with and without skills enabled.

Trial execution is simulated by default (deterministic hash-based scoring).
Real agent invocation requires wiring a concrete trial executor via the
``trial_executor`` parameter.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from agent33.evaluation.ctrf import (
    CTRFReport,
    CTRFReportGenerator,
)

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class BenchmarkTaskCategory(StrEnum):
    """Representative subset of SkillsBench task categories."""

    SCIENTIFIC_COMPUTING = "scientific_computing"
    SECURITY = "security"
    FINANCE = "finance"
    MEDIA = "media"
    DATA_ANALYSIS = "data_analysis"
    WEB = "web"
    SYSTEM_ADMIN = "system_admin"
    DEVOPS = "devops"
    AI_ML = "ai_ml"
    GENERAL = "general"


class BenchmarkRunStatus(StrEnum):
    """Lifecycle status for a benchmark run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class BenchmarkTask(BaseModel):
    """Definition of a single benchmark task."""

    task_id: str
    name: str
    category: BenchmarkTaskCategory
    description: str
    difficulty: str = "medium"  # easy, medium, hard
    required_skills: list[str] = Field(default_factory=list)
    verification_type: str = "pytest"  # pytest, output_match, file_check
    verification_config: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = 300
    enabled: bool = True


class TrialResult(BaseModel):
    """Result of a single trial execution."""

    trial_number: int
    passed: bool
    duration_ms: float
    skills_used: list[str] = Field(default_factory=list)
    error: str | None = None
    agent_output: str = ""


class TaskBenchmarkResult(BaseModel):
    """Aggregated results for a single task across multiple trials."""

    task: BenchmarkTask
    trials: list[TrialResult] = Field(default_factory=list)
    pass_rate: float = 0.0
    avg_duration_ms: float = 0.0
    skills_impact: float | None = None

    def compute_metrics(self) -> None:
        """Recompute pass_rate and avg_duration_ms from trial data."""
        if not self.trials:
            self.pass_rate = 0.0
            self.avg_duration_ms = 0.0
            return
        passed_count = sum(1 for t in self.trials if t.passed)
        self.pass_rate = passed_count / len(self.trials)
        self.avg_duration_ms = sum(t.duration_ms for t in self.trials) / len(self.trials)


class BenchmarkRun(BaseModel):
    """A complete benchmark run with configuration and results."""

    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    model_id: str = ""
    agent_id: str = ""
    with_skills: bool = True
    trials_per_task: int = 5
    task_results: list[TaskBenchmarkResult] = Field(default_factory=list)
    overall_pass_rate: float = 0.0
    total_tasks: int = 0
    passed_tasks: int = 0
    failed_tasks: int = 0
    skipped_tasks: int = 0
    status: BenchmarkRunStatus = BenchmarkRunStatus.PENDING

    def compute_summary(self) -> None:
        """Recompute summary fields from task_results."""
        self.total_tasks = len(self.task_results)
        self.passed_tasks = sum(1 for r in self.task_results if r.pass_rate >= 0.5)
        self.failed_tasks = sum(
            1 for r in self.task_results if len(r.trials) > 0 and r.pass_rate < 0.5
        )
        self.skipped_tasks = sum(1 for r in self.task_results if len(r.trials) == 0)
        if self.total_tasks > 0:
            self.overall_pass_rate = sum(r.pass_rate for r in self.task_results) / self.total_tasks
        else:
            self.overall_pass_rate = 0.0


class BenchmarkConfig(BaseModel):
    """Configuration for a benchmark run."""

    trials_per_task: int = 5
    categories: list[str] | None = None
    task_ids: list[str] | None = None
    timeout_seconds: int = 300
    with_skills: bool = True


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


class BenchmarkHarness:
    """Orchestrates benchmark task execution with multi-trial support.

    Trial execution is simulated by default using a deterministic hash-based
    scorer.  To wire real agent invocation, provide a ``trial_executor``
    callable with the signature::

        (task: BenchmarkTask, with_skills: bool) -> TrialResult

    The ``evaluation_service`` parameter is optional and reserved for future
    integration with the broader evaluation pipeline.
    """

    def __init__(
        self,
        task_catalog: list[BenchmarkTask],
        evaluation_service: Any | None = None,
    ) -> None:
        self._catalog = list(task_catalog)
        self._evaluation_service = evaluation_service
        self._runs: dict[str, BenchmarkRun] = {}
        self._run_order: list[str] = []
        self._max_runs = 500
        self._ctrf_gen = CTRFReportGenerator(
            tool_name="agent33-benchmark",
            tool_version="1.0.0",
        )

    # ------------------------------------------------------------------
    # Catalog accessors
    # ------------------------------------------------------------------

    def get_catalog(self) -> list[BenchmarkTask]:
        """Return the full task catalog."""
        return list(self._catalog)

    def get_task(self, task_id: str) -> BenchmarkTask | None:
        """Return a single task by ID, or None if not found."""
        for task in self._catalog:
            if task.task_id == task_id:
                return task
        return None

    def filter_catalog(self, config: BenchmarkConfig) -> list[BenchmarkTask]:
        """Return tasks matching the config filters."""
        tasks = [t for t in self._catalog if t.enabled]

        if config.categories:
            categories_set = set(config.categories)
            tasks = [t for t in tasks if t.category in categories_set]

        if config.task_ids:
            ids_set = set(config.task_ids)
            tasks = [t for t in tasks if t.task_id in ids_set]

        return tasks

    @staticmethod
    def load_catalog_from_file(path: Path) -> list[BenchmarkTask]:
        """Load a task catalog from a JSON file.

        The file should contain a JSON array of task objects.
        """
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError(f"Expected a JSON array in {path}, got {type(data).__name__}")
        return [BenchmarkTask.model_validate(item) for item in data]

    # ------------------------------------------------------------------
    # Trial execution
    # ------------------------------------------------------------------

    def run_trial(
        self,
        task: BenchmarkTask,
        *,
        trial_number: int = 1,
        with_skills: bool = True,
        model_id: str = "",
        agent_id: str = "",
    ) -> TrialResult:
        """Execute a single trial for a task.

        Uses deterministic hash-based simulation.  The hash seed incorporates
        the task ID, trial number, model, agent, and skills mode so that
        results are reproducible but vary across configurations.
        """
        start = time.monotonic()

        seed = f"{task.task_id}|{trial_number}|{model_id}|{agent_id}|{int(with_skills)}"
        digest = hashlib.sha256(seed.encode()).digest()
        percentile = digest[0] / 255.0

        # Tasks with more required skills benefit more from skills mode
        skills_bonus = len(task.required_skills) * 0.03 if with_skills else 0.0
        difficulty_map = {"easy": 0.75, "medium": 0.55, "hard": 0.35}
        base_threshold = difficulty_map.get(task.difficulty, 0.55)
        pass_threshold = min(1.0, base_threshold + skills_bonus)

        passed = percentile <= pass_threshold
        duration_ms = (time.monotonic() - start) * 1000

        # Simulate some skills being used
        skills_used = task.required_skills[:2] if with_skills and passed else []

        return TrialResult(
            trial_number=trial_number,
            passed=passed,
            duration_ms=round(duration_ms, 2),
            skills_used=skills_used,
            agent_output=f"simulated trial {trial_number} for {task.task_id}",
        )

    def run_task(
        self,
        task: BenchmarkTask,
        trial_count: int = 5,
        *,
        with_skills: bool = True,
        model_id: str = "",
        agent_id: str = "",
    ) -> TaskBenchmarkResult:
        """Run a single task with N trials and aggregate results."""
        trials: list[TrialResult] = []
        for i in range(1, trial_count + 1):
            trial = self.run_trial(
                task,
                trial_number=i,
                with_skills=with_skills,
                model_id=model_id,
                agent_id=agent_id,
            )
            trials.append(trial)

        result = TaskBenchmarkResult(task=task, trials=trials)
        result.compute_metrics()
        return result

    # ------------------------------------------------------------------
    # Full benchmark run
    # ------------------------------------------------------------------

    def run_benchmark(
        self,
        config: BenchmarkConfig,
        model_id: str = "",
        agent_id: str = "",
    ) -> BenchmarkRun:
        """Execute a full benchmark run across all matching tasks.

        Each task is run ``config.trials_per_task`` times.  Results are
        stored in-memory for later retrieval.
        """
        tasks = self.filter_catalog(config)

        run = BenchmarkRun(
            model_id=model_id,
            agent_id=agent_id,
            with_skills=config.with_skills,
            trials_per_task=config.trials_per_task,
            status=BenchmarkRunStatus.RUNNING,
        )

        logger.info(
            "benchmark_run_started run_id=%s tasks=%d trials_per_task=%d",
            run.run_id,
            len(tasks),
            config.trials_per_task,
        )

        try:
            for task in tasks:
                task_result = self.run_task(
                    task,
                    trial_count=config.trials_per_task,
                    with_skills=config.with_skills,
                    model_id=model_id,
                    agent_id=agent_id,
                )
                run.task_results.append(task_result)

            run.compute_summary()
            run.completed_at = datetime.now(UTC)
            run.status = BenchmarkRunStatus.COMPLETED
        except Exception as exc:
            run.status = BenchmarkRunStatus.FAILED
            run.completed_at = datetime.now(UTC)
            logger.error("benchmark_run_failed run_id=%s error=%s", run.run_id, str(exc))

        self._store_run(run)

        logger.info(
            "benchmark_run_completed run_id=%s status=%s pass_rate=%.2f",
            run.run_id,
            run.status,
            run.overall_pass_rate,
        )
        return run

    # ------------------------------------------------------------------
    # Run management
    # ------------------------------------------------------------------

    def _store_run(self, run: BenchmarkRun) -> None:
        """Store a run with bounded retention."""
        self._runs[run.run_id] = run
        self._run_order.append(run.run_id)
        if len(self._run_order) > self._max_runs:
            oldest = self._run_order.pop(0)
            self._runs.pop(oldest, None)

    def get_run(self, run_id: str) -> BenchmarkRun | None:
        """Get a benchmark run by ID."""
        return self._runs.get(run_id)

    def list_runs(self, limit: int = 50) -> list[BenchmarkRun]:
        """List benchmark runs, most recent first."""
        result: list[BenchmarkRun] = []
        for run_id in reversed(self._run_order):
            run = self._runs.get(run_id)
            if run is not None:
                result.append(run)
            if len(result) >= limit:
                break
        return result

    # ------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------

    @staticmethod
    def compare_runs(run_a: BenchmarkRun, run_b: BenchmarkRun) -> dict[str, Any]:
        """Compare two benchmark runs and compute deltas.

        Returns a dict with overall comparison and per-task breakdowns.
        This is useful for comparing with-skills vs without-skills runs,
        or for comparing different models/agents.
        """
        a_by_task: dict[str, TaskBenchmarkResult] = {r.task.task_id: r for r in run_a.task_results}
        b_by_task: dict[str, TaskBenchmarkResult] = {r.task.task_id: r for r in run_b.task_results}

        all_task_ids = sorted(set(a_by_task) | set(b_by_task))
        task_comparisons: list[dict[str, Any]] = []

        for task_id in all_task_ids:
            a_result = a_by_task.get(task_id)
            b_result = b_by_task.get(task_id)
            a_rate = a_result.pass_rate if a_result else 0.0
            b_rate = b_result.pass_rate if b_result else 0.0
            task_comparisons.append(
                {
                    "task_id": task_id,
                    "run_a_pass_rate": round(a_rate, 4),
                    "run_b_pass_rate": round(b_rate, 4),
                    "delta": round(b_rate - a_rate, 4),
                    "in_run_a": a_result is not None,
                    "in_run_b": b_result is not None,
                }
            )

        improved = sum(1 for tc in task_comparisons if tc["delta"] > 0)
        regressed = sum(1 for tc in task_comparisons if tc["delta"] < 0)
        unchanged = sum(1 for tc in task_comparisons if tc["delta"] == 0)

        return {
            "run_a_id": run_a.run_id,
            "run_b_id": run_b.run_id,
            "run_a_overall_pass_rate": round(run_a.overall_pass_rate, 4),
            "run_b_overall_pass_rate": round(run_b.overall_pass_rate, 4),
            "overall_delta": round(run_b.overall_pass_rate - run_a.overall_pass_rate, 4),
            "run_a_model": run_a.model_id,
            "run_b_model": run_b.model_id,
            "run_a_with_skills": run_a.with_skills,
            "run_b_with_skills": run_b.with_skills,
            "tasks_compared": len(task_comparisons),
            "tasks_improved": improved,
            "tasks_regressed": regressed,
            "tasks_unchanged": unchanged,
            "task_comparisons": task_comparisons,
        }

    # ------------------------------------------------------------------
    # CTRF export
    # ------------------------------------------------------------------

    def to_ctrf(self, run: BenchmarkRun) -> CTRFReport:
        """Convert a benchmark run to a CTRF report."""
        results_dicts: list[dict[str, Any]] = []
        for task_result in run.task_results:
            status = "pass" if task_result.pass_rate >= 0.5 else "fail"
            results_dicts.append(
                {
                    "item_id": task_result.task.task_id,
                    "result": status,
                    "duration_ms": task_result.avg_duration_ms,
                    "notes": (
                        f"pass_rate={task_result.pass_rate:.2f} "
                        f"trials={len(task_result.trials)} "
                        f"category={task_result.task.category}"
                    ),
                    "tags": [
                        task_result.task.category,
                        task_result.task.difficulty,
                        f"trials:{len(task_result.trials)}",
                    ],
                }
            )

        start_ms = int(run.started_at.timestamp() * 1000)
        stop_ms = int(run.completed_at.timestamp() * 1000) if run.completed_at else start_ms

        return self._ctrf_gen.from_evaluation_run(results_dicts, start_ms, stop_ms)
