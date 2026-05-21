"""Tests for SkillsBench Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent33.benchmarks.skillsbench.models import (
    BenchmarkRunResult,
    BenchmarkRunStatus,
    TaskFilter,
    TrialArtifact,
    TrialOutcome,
    TrialRecord,
)

# ---------------------------------------------------------------------------
# TrialOutcome enum
# ---------------------------------------------------------------------------


class TestTrialOutcome:
    def test_values(self) -> None:
        assert TrialOutcome.PASSED == "passed"
        assert TrialOutcome.FAILED == "failed"
        assert TrialOutcome.ERROR == "error"
        assert TrialOutcome.TIMEOUT == "timeout"
        assert TrialOutcome.SKIPPED == "skipped"

    def test_all_variants_accessible(self) -> None:
        """Every TrialOutcome variant should be usable as a string."""
        for variant in TrialOutcome:
            assert isinstance(variant.value, str)
            assert len(variant.value) > 0


# ---------------------------------------------------------------------------
# TrialRecord
# ---------------------------------------------------------------------------


class TestTrialRecord:
    def test_minimal_creation(self) -> None:
        record = TrialRecord(
            task_id="math/addition",
            trial_number=1,
            outcome=TrialOutcome.PASSED,
        )
        assert record.task_id == "math/addition"
        assert record.trial_number == 1
        assert record.outcome == TrialOutcome.PASSED
        assert record.passed is True
        assert record.tokens_used == 0
        assert record.skills_enabled is False

    def test_passed_property_true(self) -> None:
        record = TrialRecord(task_id="x/y", trial_number=1, outcome=TrialOutcome.PASSED)
        assert record.passed is True

    def test_passed_property_false_on_failure(self) -> None:
        record = TrialRecord(task_id="x/y", trial_number=1, outcome=TrialOutcome.FAILED)
        assert record.passed is False

    def test_passed_property_false_on_error(self) -> None:
        record = TrialRecord(task_id="x/y", trial_number=1, outcome=TrialOutcome.ERROR)
        assert record.passed is False

    def test_full_fields(self) -> None:
        record = TrialRecord(
            task_id="scientific_computing/fft",
            trial_number=3,
            outcome=TrialOutcome.FAILED,
            duration_ms=1500.5,
            tokens_used=4200,
            agent="code-worker",
            model="gpt-4o",
            skills_enabled=True,
            iterations=5,
            tool_calls_made=12,
            termination_reason="max_iterations",
            pytest_returncode=1,
            error_message="",
            pytest_stdout_excerpt="stdout",
            pytest_stderr_excerpt="stderr",
            artifacts=[
                TrialArtifact(
                    name="pytest-stdout.txt",
                    kind="pytest_stdout",
                    relative_path="trials/math__addition/trial-01/pytest-stdout.txt",
                )
            ],
            metadata={"custom_key": "value"},
        )
        assert record.duration_ms == 1500.5
        assert record.tokens_used == 4200
        assert record.agent == "code-worker"
        assert record.model == "gpt-4o"
        assert record.skills_enabled is True
        assert record.iterations == 5
        assert record.tool_calls_made == 12
        assert record.termination_reason == "max_iterations"
        assert record.pytest_returncode == 1
        assert record.pytest_stdout_excerpt == "stdout"
        assert record.pytest_stderr_excerpt == "stderr"
        assert record.artifacts[0].kind == "pytest_stdout"
        assert record.metadata["custom_key"] == "value"

    def test_trial_number_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            TrialRecord(task_id="x/y", trial_number=0, outcome=TrialOutcome.PASSED)

    def test_tokens_used_cannot_be_negative(self) -> None:
        with pytest.raises(ValidationError):
            TrialRecord(task_id="x/y", trial_number=1, outcome=TrialOutcome.PASSED, tokens_used=-1)


# ---------------------------------------------------------------------------
# TaskFilter
# ---------------------------------------------------------------------------


class TestTaskFilter:
    def test_default_filter_is_empty(self) -> None:
        f = TaskFilter()
        assert f.categories == []
        assert f.exclude_categories == []
        assert f.task_ids == []
        assert f.max_tasks == 0

    def test_category_filter(self) -> None:
        f = TaskFilter(categories=["math", "science"])
        assert "math" in f.categories
        assert "science" in f.categories

    def test_exclude_categories(self) -> None:
        f = TaskFilter(exclude_categories=["slow_tasks"])
        assert "slow_tasks" in f.exclude_categories

    def test_task_id_filter(self) -> None:
        f = TaskFilter(task_ids=["math/add", "math/subtract"])
        assert len(f.task_ids) == 2

    def test_max_tasks_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            TaskFilter(max_tasks=-1)


# ---------------------------------------------------------------------------
# BenchmarkRunResult
# ---------------------------------------------------------------------------


class TestBenchmarkRunResult:
    def test_default_creation(self) -> None:
        result = BenchmarkRunResult()
        assert result.status == BenchmarkRunStatus.PENDING
        assert result.total_tasks == 0
        assert result.trials == []
        assert result.pass_rate == 0.0

    def test_compute_aggregates_empty(self) -> None:
        result = BenchmarkRunResult()
        result.compute_aggregates()
        assert result.total_trials == 0
        assert result.passed_trials == 0
        assert result.pass_rate == 0.0
        assert result.total_tasks == 0

    def test_compute_aggregates_with_trials(self) -> None:
        trials = [
            TrialRecord(
                task_id="math/add",
                trial_number=1,
                outcome=TrialOutcome.PASSED,
                tokens_used=100,
                duration_ms=50.0,
            ),
            TrialRecord(
                task_id="math/add",
                trial_number=2,
                outcome=TrialOutcome.FAILED,
                tokens_used=200,
                duration_ms=75.0,
            ),
            TrialRecord(
                task_id="science/chem",
                trial_number=1,
                outcome=TrialOutcome.PASSED,
                tokens_used=150,
                duration_ms=60.0,
            ),
            TrialRecord(
                task_id="science/chem",
                trial_number=2,
                outcome=TrialOutcome.ERROR,
                tokens_used=50,
                duration_ms=10.0,
            ),
        ]
        result = BenchmarkRunResult(trials=trials)
        result.compute_aggregates()

        assert result.total_trials == 4
        assert result.total_tasks == 2
        assert result.passed_trials == 2
        assert result.failed_trials == 1
        assert result.error_trials == 1
        assert result.total_tokens_used == 500
        assert result.total_duration_ms == 195.0
        assert result.pass_rate == 0.5
        assert len(result.task_summaries) == 2
        assert result.task_summaries[0].task_id == "math/add"

    def test_compute_aggregates_all_passed(self) -> None:
        trials = [
            TrialRecord(
                task_id="a/b",
                trial_number=i,
                outcome=TrialOutcome.PASSED,
            )
            for i in range(1, 6)
        ]
        result = BenchmarkRunResult(trials=trials)
        result.compute_aggregates()
        assert result.pass_rate == 1.0
        assert result.passed_trials == 5
        assert result.task_summaries[0].pass_rate == 1.0

    def test_compute_aggregates_all_failed(self) -> None:
        trials = [
            TrialRecord(
                task_id="a/b",
                trial_number=i,
                outcome=TrialOutcome.FAILED,
            )
            for i in range(1, 4)
        ]
        result = BenchmarkRunResult(trials=trials)
        result.compute_aggregates()
        assert result.pass_rate == 0.0
        assert result.failed_trials == 3

    def test_status_values(self) -> None:
        assert BenchmarkRunStatus.PENDING == "pending"
        assert BenchmarkRunStatus.RUNNING == "running"
        assert BenchmarkRunStatus.COMPLETED == "completed"
        assert BenchmarkRunStatus.FAILED == "failed"
        assert BenchmarkRunStatus.CANCELLED == "cancelled"
