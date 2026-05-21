"""Pydantic models for SkillsBench benchmark runs and trial results."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class TrialOutcome(StrEnum):
    """Outcome of a single SkillsBench trial."""

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


class BenchmarkRunStatus(StrEnum):
    """Status of a full benchmark run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TrialArtifact(BaseModel):
    """Persisted artifact produced for a single benchmark trial."""

    name: str = Field(..., description="Human-readable artifact label.")
    kind: str = Field(..., description="Artifact category, e.g. pytest_stdout.")
    relative_path: str = Field(..., description="Artifact path relative to the run directory.")
    content_type: str = Field(default="text/plain", description="Artifact MIME type.")
    size_bytes: int = Field(default=0, ge=0)
    preview: str = Field(default="", description="Short excerpt for API responses.")


class TrialRecord(BaseModel):
    """Record of a single trial execution."""

    task_id: str = Field(..., description="SkillsBench task ID (category/task_name).")
    trial_number: int = Field(..., ge=1, description="Trial number within this task.")
    outcome: TrialOutcome = Field(..., description="Trial outcome.")
    duration_ms: float = Field(default=0.0, ge=0.0, description="Wall-clock time in ms.")
    tokens_used: int = Field(default=0, ge=0, description="Total tokens consumed.")
    agent: str = Field(default="", description="Agent name used for the trial.")
    model: str = Field(default="", description="LLM model used for the trial.")
    skills_enabled: bool = Field(default=False, description="Whether skills were enabled.")
    iterations: int = Field(default=0, ge=0, description="Iterative loop iterations.")
    tool_calls_made: int = Field(default=0, ge=0, description="Number of tool calls made.")
    termination_reason: str = Field(default="", description="Why the agent stopped.")
    pytest_returncode: int = Field(default=-1, description="Raw pytest return code.")
    error_message: str = Field(default="", description="Error details if outcome is ERROR.")
    pytest_stdout_excerpt: str = Field(default="", description="Short excerpt from pytest stdout.")
    pytest_stderr_excerpt: str = Field(default="", description="Short excerpt from pytest stderr.")
    artifacts: list[TrialArtifact] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict, description="Extra metadata.")

    @property
    def passed(self) -> bool:
        """Whether this trial passed."""
        return self.outcome == TrialOutcome.PASSED


class TaskFilter(BaseModel):
    """Filter criteria for selecting SkillsBench tasks."""

    categories: list[str] = Field(
        default_factory=list,
        description="Include only these categories. Empty means all.",
    )
    exclude_categories: list[str] = Field(
        default_factory=list,
        description="Exclude these categories.",
    )
    task_ids: list[str] = Field(
        default_factory=list,
        description="Include only specific task IDs. Empty means all.",
    )
    max_tasks: int = Field(
        default=0,
        ge=0,
        description="Maximum number of tasks to include. 0 means unlimited.",
    )


class TaskBenchmarkSummary(BaseModel):
    """Per-task rollup for a benchmark run."""

    task_id: str
    category: str
    total_trials: int = Field(default=0, ge=0)
    passed_trials: int = Field(default=0, ge=0)
    failed_trials: int = Field(default=0, ge=0)
    error_trials: int = Field(default=0, ge=0)
    pass_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    avg_duration_ms: float = Field(default=0.0, ge=0.0)
    total_tokens_used: int = Field(default=0, ge=0)


class BenchmarkRunResult(BaseModel):
    """Aggregated result of a complete SkillsBench benchmark run."""

    run_id: str = Field(default="", description="Unique run identifier.")
    status: BenchmarkRunStatus = Field(default=BenchmarkRunStatus.PENDING)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = Field(default=None)
    config_summary: dict[str, Any] = Field(
        default_factory=dict,
        description="Configuration snapshot for this run.",
    )
    trials: list[TrialRecord] = Field(default_factory=list)
    total_tasks: int = Field(default=0, ge=0)
    total_trials: int = Field(default=0, ge=0)
    passed_trials: int = Field(default=0, ge=0)
    failed_trials: int = Field(default=0, ge=0)
    error_trials: int = Field(default=0, ge=0)
    pass_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    total_tokens_used: int = Field(default=0, ge=0)
    total_duration_ms: float = Field(default=0.0, ge=0.0)
    task_summaries: list[TaskBenchmarkSummary] = Field(default_factory=list)
    artifact_root: str = Field(default="", description="Relative storage directory for this run.")
    ctrf_report_path: str = Field(default="", description="Relative path to the CTRF report.")

    def compute_aggregates(self) -> None:
        """Recompute aggregate fields from the trials list."""
        self.total_trials = len(self.trials)
        self.passed_trials = sum(1 for t in self.trials if t.outcome == TrialOutcome.PASSED)
        self.failed_trials = sum(1 for t in self.trials if t.outcome == TrialOutcome.FAILED)
        self.error_trials = sum(1 for t in self.trials if t.outcome == TrialOutcome.ERROR)
        self.total_tokens_used = sum(t.tokens_used for t in self.trials)
        self.total_duration_ms = sum(t.duration_ms for t in self.trials)
        self.pass_rate = self.passed_trials / self.total_trials if self.total_trials > 0 else 0.0
        task_ids = {t.task_id for t in self.trials}
        self.total_tasks = len(task_ids)
        self.task_summaries = self._build_task_summaries()

    def _build_task_summaries(self) -> list[TaskBenchmarkSummary]:
        """Build per-task aggregate summaries from trial records."""
        grouped: dict[str, list[TrialRecord]] = {}
        for trial in self.trials:
            grouped.setdefault(trial.task_id, []).append(trial)

        summaries: list[TaskBenchmarkSummary] = []
        for task_id in sorted(grouped):
            trials = grouped[task_id]
            total_trials = len(trials)
            passed_trials = sum(1 for trial in trials if trial.outcome == TrialOutcome.PASSED)
            failed_trials = sum(1 for trial in trials if trial.outcome == TrialOutcome.FAILED)
            error_trials = sum(1 for trial in trials if trial.outcome == TrialOutcome.ERROR)
            category = task_id.split("/", 1)[0] if "/" in task_id else ""
            summaries.append(
                TaskBenchmarkSummary(
                    task_id=task_id,
                    category=category,
                    total_trials=total_trials,
                    passed_trials=passed_trials,
                    failed_trials=failed_trials,
                    error_trials=error_trials,
                    pass_rate=passed_trials / total_trials if total_trials else 0.0,
                    avg_duration_ms=(
                        sum(trial.duration_ms for trial in trials) / total_trials
                        if total_trials
                        else 0.0
                    ),
                    total_tokens_used=sum(trial.tokens_used for trial in trials),
                )
            )
        return summaries
