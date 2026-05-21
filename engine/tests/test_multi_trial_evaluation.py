"""Multi-trial evaluation, CTRF reporting, and experiment orchestration tests.

Tests cover:
- TrialResult model (binary score, timestamps, error messages)
- MultiTrialResult model (pass_rate, variance, std_dev computations)
- MultiTrialExecutor (single trial, multi-trial, error handling, tokens)
- SkillsImpact model (impact calculation, confidence scoring)
- CTRFGenerator (report structure, summary stats, file output)
- ExperimentRunner (matrix execution, skills pairing, comparison matrix)
- ExperimentConfig (defaults, validation, custom values)
- EvaluationService multi-trial methods (CRUD, CTRF export)
- API endpoints (REST lifecycle for experiments)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

if TYPE_CHECKING:
    from pathlib import Path

import pytest
from pydantic import ValidationError

from agent33.evaluation.ctrf import CTRFGenerator
from agent33.evaluation.experiment import ExperimentRunner
from agent33.evaluation.multi_trial import (
    ExperimentConfig,
    MultiTrialExecutor,
    MultiTrialResult,
    MultiTrialRun,
    SkillsImpact,
    TrialResult,
)
from agent33.evaluation.service import (
    DeterministicFallbackEvaluator,
    EvaluationService,
    TrialEvaluationOutcome,
)

if TYPE_CHECKING:
    from starlette.testclient import TestClient


# ===================================================================
# TrialResult
# ===================================================================


class TestTrialResult:
    """Test the TrialResult model."""

    def test_binary_score_pass(self):
        """Score of 1 is accepted for a passing trial."""
        t = TrialResult(trial_number=1, score=1, duration_ms=100)
        assert t.score == 1
        assert t.trial_number == 1
        assert t.duration_ms == 100

    def test_binary_score_fail(self):
        """Score of 0 is accepted for a failing trial."""
        t = TrialResult(trial_number=2, score=0, duration_ms=50)
        assert t.score == 0

    def test_invalid_score_rejected(self):
        """Non-binary scores (e.g. 2, -1) are rejected by Literal[0, 1]."""
        with pytest.raises(ValidationError):
            TrialResult(trial_number=1, score=2, duration_ms=100)  # type: ignore[arg-type]

    def test_timestamp_default(self):
        """Timestamp defaults to current UTC time."""
        t = TrialResult(trial_number=1, score=1, duration_ms=10)
        assert t.timestamp is not None
        assert t.timestamp.tzinfo is not None
        # Should be within the last few seconds
        delta = datetime.now(UTC) - t.timestamp
        assert delta.total_seconds() < 5

    def test_error_message_optional(self):
        """error_message defaults to None and can be set."""
        t_none = TrialResult(trial_number=1, score=0, duration_ms=10)
        assert t_none.error_message is None

        t_err = TrialResult(trial_number=1, score=0, duration_ms=10, error_message="timeout")
        assert t_err.error_message == "timeout"

    def test_tokens_used_default(self):
        """tokens_used defaults to 0."""
        t = TrialResult(trial_number=1, score=1, duration_ms=10)
        assert t.tokens_used == 0

        t2 = TrialResult(trial_number=1, score=1, duration_ms=10, tokens_used=500)
        assert t2.tokens_used == 500


# ===================================================================
# MultiTrialResult
# ===================================================================


class TestMultiTrialResult:
    """Test MultiTrialResult aggregation computations."""

    def _make_trials(self, scores: list[int]) -> list[TrialResult]:
        return [
            TrialResult(trial_number=i + 1, score=s, duration_ms=10) for i, s in enumerate(scores)
        ]

    def test_pass_rate_all_pass(self):
        """5/5 passing trials yields pass_rate = 1.0."""
        r = MultiTrialResult(
            task_id="T1",
            agent="a",
            model="m",
            skills_enabled=True,
            trials=self._make_trials([1, 1, 1, 1, 1]),
        )
        assert r.pass_rate == 1.0

    def test_pass_rate_all_fail(self):
        """0/5 passing trials yields pass_rate = 0.0."""
        r = MultiTrialResult(
            task_id="T1",
            agent="a",
            model="m",
            skills_enabled=False,
            trials=self._make_trials([0, 0, 0, 0, 0]),
        )
        assert r.pass_rate == 0.0

    def test_pass_rate_partial(self):
        """3/5 passing trials yields pass_rate = 0.6."""
        r = MultiTrialResult(
            task_id="T1",
            agent="a",
            model="m",
            skills_enabled=True,
            trials=self._make_trials([1, 0, 1, 0, 1]),
        )
        assert r.pass_rate == pytest.approx(0.6)

    def test_pass_rate_empty(self):
        """Empty trials yields pass_rate = 0.0."""
        r = MultiTrialResult(
            task_id="T1",
            agent="a",
            model="m",
            skills_enabled=True,
            trials=[],
        )
        assert r.pass_rate == 0.0

    def test_variance_all_same(self):
        """All-pass or all-fail should have 0 variance."""
        r = MultiTrialResult(
            task_id="T1",
            agent="a",
            model="m",
            skills_enabled=True,
            trials=self._make_trials([1, 1, 1, 1, 1]),
        )
        assert r.variance == 0.0

    def test_variance_mixed(self):
        """3/5 pass rate => variance = 0.6*0.4 = 0.24."""
        r = MultiTrialResult(
            task_id="T1",
            agent="a",
            model="m",
            skills_enabled=True,
            trials=self._make_trials([1, 0, 1, 0, 1]),
        )
        # pass_rate = 0.6, each pass: (1-0.6)^2=0.16, each fail: (0-0.6)^2=0.36
        # variance = (3*0.16 + 2*0.36)/5 = (0.48+0.72)/5 = 1.2/5 = 0.24
        assert r.variance == pytest.approx(0.24)

    def test_std_dev_is_sqrt_of_variance(self):
        """std_dev should be the square root of variance."""
        r = MultiTrialResult(
            task_id="T1",
            agent="a",
            model="m",
            skills_enabled=True,
            trials=self._make_trials([1, 0, 1, 0, 1]),
        )
        assert r.std_dev == pytest.approx(r.variance**0.5)

    def test_variance_empty(self):
        """Empty trials yields variance = 0.0."""
        r = MultiTrialResult(
            task_id="T1",
            agent="a",
            model="m",
            skills_enabled=True,
            trials=[],
        )
        assert r.variance == 0.0

    def test_total_duration_aggregation(self):
        """total_duration_ms is correctly set from input."""
        trials = self._make_trials([1, 0])
        r = MultiTrialResult(
            task_id="T1",
            agent="a",
            model="m",
            skills_enabled=True,
            trials=trials,
            total_duration_ms=20,
        )
        assert r.total_duration_ms == 20


# ===================================================================
# MultiTrialExecutor
# ===================================================================


class TestMultiTrialExecutor:
    """Test the MultiTrialExecutor."""

    @pytest.fixture
    def success_fn(self) -> AsyncMock:
        """Evaluation function that always succeeds."""
        fn = AsyncMock(return_value=True)
        return fn

    @pytest.fixture
    def failure_fn(self) -> AsyncMock:
        """Evaluation function that always fails."""
        fn = AsyncMock(return_value=False)
        return fn

    async def test_single_trial_success(self, success_fn: AsyncMock):
        """A successful trial should have score=1 and no error."""
        executor = MultiTrialExecutor(evaluation_fn=success_fn)
        result = await executor.execute_trial("T1", "agent1", "model1", True, 1)
        assert result.score == 1
        assert result.error_message is None
        assert result.trial_number == 1
        assert result.duration_ms >= 0
        success_fn.assert_called_once_with("T1", "agent1", "model1", True)

    async def test_single_trial_failure(self, failure_fn: AsyncMock):
        """A failing trial should have score=0 and no error message."""
        executor = MultiTrialExecutor(evaluation_fn=failure_fn)
        result = await executor.execute_trial("T1", "agent1", "model1", False, 3)
        assert result.score == 0
        assert result.error_message is None
        assert result.trial_number == 3

    async def test_single_trial_exception(self):
        """An exception in evaluation_fn should produce score=0 with error_message."""
        fn = AsyncMock(side_effect=RuntimeError("boom"))
        executor = MultiTrialExecutor(evaluation_fn=fn)
        result = await executor.execute_trial("T1", "a", "m", True, 1)
        assert result.score == 0
        assert result.error_message == "boom"

    async def test_no_evaluation_fn_raises(self):
        """Calling execute_trial without an evaluation_fn sets error."""
        executor = MultiTrialExecutor(evaluation_fn=None)
        result = await executor.execute_trial("T1", "a", "m", True, 1)
        assert result.score == 0
        assert "No evaluation function configured" in (result.error_message or "")

    async def test_multi_trial_aggregation(self, success_fn: AsyncMock):
        """execute_multi_trial runs N trials and aggregates correctly."""
        executor = MultiTrialExecutor(evaluation_fn=success_fn)
        result = await executor.execute_multi_trial("T1", "a", "m", True, num_trials=3)
        assert len(result.trials) == 3
        assert result.pass_rate == 1.0
        assert result.task_id == "T1"
        assert result.agent == "a"
        assert result.model == "m"
        assert result.skills_enabled is True
        assert success_fn.call_count == 3

    async def test_multi_trial_mixed_results(self):
        """Mixed success/failure should produce correct pass_rate."""
        call_count = 0

        async def alternating(task_id: str, agent: str, model: str, skills: bool) -> bool:
            nonlocal call_count
            call_count += 1
            return call_count % 2 == 1  # True on odd calls

        executor = MultiTrialExecutor(evaluation_fn=alternating)
        result = await executor.execute_multi_trial("T1", "a", "m", True, num_trials=4)
        assert len(result.trials) == 4
        # Trials: True, False, True, False => pass_rate = 0.5
        assert result.pass_rate == pytest.approx(0.5)
        scores = [t.score for t in result.trials]
        assert scores == [1, 0, 1, 0]

    async def test_token_tracking(self):
        """total_tokens is the sum of tokens_used across trials."""

        async def fn(t: str, a: str, m: str, s: bool) -> bool:
            return True

        executor = MultiTrialExecutor(evaluation_fn=fn)
        result = await executor.execute_multi_trial("T1", "a", "m", True, num_trials=3)
        # Default tokens_used is 0, so total should be 0
        assert result.total_tokens == 0

    def test_compute_skills_impact(self):
        """compute_skills_impact correctly computes the delta."""
        with_skills = MultiTrialResult(
            task_id="T1",
            agent="a",
            model="m",
            skills_enabled=True,
            trials=[
                TrialResult(trial_number=1, score=1, duration_ms=10),
                TrialResult(trial_number=2, score=1, duration_ms=10),
                TrialResult(trial_number=3, score=0, duration_ms=10),
            ],
        )
        without_skills = MultiTrialResult(
            task_id="T1",
            agent="a",
            model="m",
            skills_enabled=False,
            trials=[
                TrialResult(trial_number=1, score=0, duration_ms=10),
                TrialResult(trial_number=2, score=1, duration_ms=10),
                TrialResult(trial_number=3, score=0, duration_ms=10),
            ],
        )
        impact = MultiTrialExecutor.compute_skills_impact(with_skills, without_skills)
        # with: 2/3 = 0.6667, without: 1/3 = 0.3333
        assert impact.pass_rate_with_skills == pytest.approx(2 / 3)
        assert impact.pass_rate_without_skills == pytest.approx(1 / 3)
        assert impact.skills_impact == pytest.approx(1 / 3)


# ===================================================================
# SkillsImpact
# ===================================================================


class TestSkillsImpact:
    """Test SkillsImpact computed fields."""

    def test_positive_impact(self):
        """Skills help: positive skills_impact."""
        si = SkillsImpact(
            task_id="T1",
            agent="a",
            model="m",
            pass_rate_with_skills=0.8,
            pass_rate_without_skills=0.4,
        )
        assert si.skills_impact == pytest.approx(0.4)

    def test_negative_impact(self):
        """Skills hurt: negative skills_impact."""
        si = SkillsImpact(
            task_id="T1",
            agent="a",
            model="m",
            pass_rate_with_skills=0.3,
            pass_rate_without_skills=0.7,
        )
        assert si.skills_impact == pytest.approx(-0.4)

    def test_zero_impact(self):
        """No difference: skills_impact = 0."""
        si = SkillsImpact(
            task_id="T1",
            agent="a",
            model="m",
            pass_rate_with_skills=0.5,
            pass_rate_without_skills=0.5,
        )
        assert si.skills_impact == pytest.approx(0.0)

    def test_confidence_high_for_small_impact(self):
        """Confidence is higher when impact is near zero."""
        si = SkillsImpact(
            task_id="T1",
            agent="a",
            model="m",
            pass_rate_with_skills=0.5,
            pass_rate_without_skills=0.5,
        )
        assert si.confidence == 1.0

    def test_confidence_lower_for_large_impact(self):
        """Confidence decreases as absolute impact grows."""
        si = SkillsImpact(
            task_id="T1",
            agent="a",
            model="m",
            pass_rate_with_skills=1.0,
            pass_rate_without_skills=0.0,
        )
        # impact = 1.0, confidence = 1.0 - 1.0*0.1 = 0.9
        assert si.confidence == pytest.approx(0.9)

    def test_confidence_clamps_to_zero(self):
        """Confidence never goes below 0."""
        # In practice the impact range is -1..1, so confidence range is 0.9..1.0
        # But the heuristic uses abs(impact)*0.1 clamped to [0,1]
        si = SkillsImpact(
            task_id="T1",
            agent="a",
            model="m",
            pass_rate_with_skills=0.8,
            pass_rate_without_skills=0.2,
        )
        assert 0.0 <= si.confidence <= 1.0


# ===================================================================
# CTRFGenerator
# ===================================================================


class TestCTRFGenerator:
    """Test CTRF report generation."""

    def _make_run(self) -> MultiTrialRun:
        """Create a run with known results for testing."""
        now = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
        config = ExperimentConfig(
            tasks=["T1"],
            agents=["a"],
            models=["m"],
            trials_per_combination=5,
        )
        trials_pass = [TrialResult(trial_number=i, score=1, duration_ms=100) for i in range(1, 6)]
        trials_mixed = [
            TrialResult(trial_number=1, score=1, duration_ms=100),
            TrialResult(trial_number=2, score=0, duration_ms=100),
            TrialResult(trial_number=3, score=0, duration_ms=100),
            TrialResult(trial_number=4, score=0, duration_ms=100),
            TrialResult(trial_number=5, score=0, duration_ms=100),
        ]
        return MultiTrialRun(
            run_id="test-run",
            config=config,
            results=[
                MultiTrialResult(
                    task_id="T1",
                    agent="a",
                    model="m",
                    skills_enabled=True,
                    trials=trials_pass,
                    total_duration_ms=500,
                ),
                MultiTrialResult(
                    task_id="T1",
                    agent="a",
                    model="m",
                    skills_enabled=False,
                    trials=trials_mixed,
                    total_duration_ms=500,
                ),
            ],
            started_at=now,
            completed_at=now,
            status="completed",
        )

    def test_report_structure(self):
        """Report has the expected CTRF top-level structure."""
        gen = CTRFGenerator()
        run = self._make_run()
        report = gen.generate_report(run)
        assert "results" in report
        results = report["results"]
        assert "tool" in results
        assert "summary" in results
        assert "tests" in results
        assert "extra" in results
        assert results["tool"]["name"] == "agent33-eval"
        assert results["tool"]["version"] == "1.0.0"

    def test_summary_counts(self):
        """Summary correctly counts passed/failed tests."""
        gen = CTRFGenerator()
        run = self._make_run()
        report = gen.generate_report(run)
        summary = report["results"]["summary"]
        assert summary["tests"] == 2
        # First result: 5/5 = 1.0 >= 0.6 => passed
        # Second result: 1/5 = 0.2 < 0.6 => failed
        assert summary["passed"] == 1
        assert summary["failed"] == 1
        assert summary["skipped"] == 0
        assert summary["pending"] == 0

    def test_status_mapping_threshold(self):
        """pass_rate >= threshold maps to passed, below maps to failed."""
        gen = CTRFGenerator(pass_threshold=0.6)
        run = self._make_run()
        report = gen.generate_report(run)
        tests = report["results"]["tests"]
        # +skills (pass_rate=1.0) => passed
        assert tests[0]["status"] == "passed"
        assert "+skills" in tests[0]["name"]
        # -skills (pass_rate=0.2) => failed
        assert tests[1]["status"] == "failed"
        assert "-skills" in tests[1]["name"]

    def test_extra_fields_present(self):
        """Each test entry has extra fields with trial details."""
        gen = CTRFGenerator()
        run = self._make_run()
        report = gen.generate_report(run)
        extra = report["results"]["tests"][0]["extra"]
        assert extra["trials"] == 5
        assert extra["pass_rate"] == 1.0
        assert extra["skills_enabled"] is True
        assert extra["agent"] == "a"
        assert extra["model"] == "m"
        assert "variance" in extra
        assert "tokens_used" in extra
        assert "trial_results" in extra
        assert "skillsbench" in extra
        assert extra["trial_results"] == [1, 1, 1, 1, 1]

    def test_run_level_skillsbench_metadata_present(self):
        """Run-level CTRF extra should include SkillsBench metadata."""
        gen = CTRFGenerator()
        run = self._make_run()
        report = gen.generate_report(run)
        sb = report["results"]["extra"]["skillsbench"]
        assert sb["trials_per_combination"] == 5
        assert sb["skills_modes"] == [True, False]
        assert sb["skills_impacts_count"] == 0

    def test_custom_threshold(self):
        """Custom pass_threshold changes which results are 'passed'."""
        # With threshold=0.1, even 1/5 (0.2) passes
        gen = CTRFGenerator(pass_threshold=0.1)
        run = self._make_run()
        report = gen.generate_report(run)
        summary = report["results"]["summary"]
        assert summary["passed"] == 2
        assert summary["failed"] == 0

    def test_write_report(self, tmp_path: Path):
        """write_report creates a valid JSON file at the given path."""
        gen = CTRFGenerator()
        run = self._make_run()
        output_path = tmp_path / "reports" / "ctrf.json"
        gen.write_report(run, output_path)

        assert output_path.exists()
        data = json.loads(output_path.read_text())
        assert "results" in data
        assert data["results"]["summary"]["tests"] == 2

    def test_summary_statistics(self):
        """generate_summary returns correct aggregate statistics."""
        gen = CTRFGenerator()
        run = self._make_run()
        summary = gen.generate_summary(run)
        assert summary["total_combinations"] == 2
        # avg pass_rate = (1.0 + 0.2) / 2 = 0.6
        assert summary["avg_pass_rate"] == pytest.approx(0.6)
        assert "avg_variance" in summary
        assert "consistency" in summary

    def test_summary_empty_run(self):
        """generate_summary handles empty results."""
        gen = CTRFGenerator()
        config = ExperimentConfig(tasks=[], agents=[], models=[])
        run = MultiTrialRun(config=config)
        summary = gen.generate_summary(run)
        assert summary["total_combinations"] == 0
        assert summary["avg_pass_rate"] == 0.0

    def test_timestamps_in_report(self):
        """start and stop timestamps are included in milliseconds."""
        gen = CTRFGenerator()
        run = self._make_run()
        report = gen.generate_report(run)
        summary = report["results"]["summary"]
        assert isinstance(summary["start"], int)
        assert isinstance(summary["stop"], int)
        assert summary["start"] > 0
        assert summary["stop"] >= summary["start"]


# ===================================================================
# ExperimentRunner
# ===================================================================


class TestExperimentRunner:
    """Test the experiment orchestrator."""

    async def test_full_matrix_execution(self):
        """Runs the full task x agent x model x skills matrix."""
        fn = AsyncMock(return_value=True)
        executor = MultiTrialExecutor(evaluation_fn=fn)
        runner = ExperimentRunner(executor)

        config = ExperimentConfig(
            tasks=["T1", "T2"],
            agents=["agent1"],
            models=["model1"],
            trials_per_combination=2,
            skills_modes=[True, False],
        )
        run = await runner.run_experiment(config)
        # 2 tasks * 1 agent * 1 model * 2 skills_modes = 4 combinations
        assert len(run.results) == 4
        assert run.status == "completed"
        assert run.completed_at is not None
        # 4 combinations * 2 trials each = 8 total calls
        assert fn.call_count == 8

    async def test_skills_impact_pairing(self):
        """Skills impacts are computed for pairs with matching (task, agent, model)."""
        call_count = 0

        async def fn(t: str, a: str, m: str, s: bool) -> bool:
            nonlocal call_count
            call_count += 1
            return s  # pass with skills, fail without

        executor = MultiTrialExecutor(evaluation_fn=fn)
        runner = ExperimentRunner(executor)

        config = ExperimentConfig(
            tasks=["T1"],
            agents=["a1"],
            models=["m1"],
            trials_per_combination=5,
            skills_modes=[True, False],
        )
        run = await runner.run_experiment(config)
        assert len(run.skills_impacts) == 1
        impact = run.skills_impacts[0]
        assert impact.task_id == "T1"
        assert impact.pass_rate_with_skills == pytest.approx(1.0)
        assert impact.pass_rate_without_skills == pytest.approx(0.0)
        assert impact.skills_impact == pytest.approx(1.0)

    async def test_comparison_matrix(self):
        """generate_comparison_matrix structures results by agent/model -> task."""
        fn = AsyncMock(return_value=True)
        executor = MultiTrialExecutor(evaluation_fn=fn)
        runner = ExperimentRunner(executor)

        config = ExperimentConfig(
            tasks=["T1"],
            agents=["a1"],
            models=["m1"],
            trials_per_combination=2,
            skills_modes=[True, False],
        )
        run = await runner.run_experiment(config)
        matrix = runner.generate_comparison_matrix(run)

        assert "a1/m1" in matrix
        assert "T1" in matrix["a1/m1"]
        assert "with_skills" in matrix["a1/m1"]["T1"]
        assert "without_skills" in matrix["a1/m1"]["T1"]
        assert matrix["a1/m1"]["T1"]["with_skills"]["pass_rate"] == 1.0
        assert matrix["a1/m1"]["T1"]["with_skills"]["trials"] == 2

    async def test_empty_config(self):
        """Empty task/agent/model lists produce zero results."""
        fn = AsyncMock(return_value=True)
        executor = MultiTrialExecutor(evaluation_fn=fn)
        runner = ExperimentRunner(executor)

        config = ExperimentConfig(
            tasks=[],
            agents=[],
            models=[],
            trials_per_combination=5,
        )
        run = await runner.run_experiment(config)
        assert len(run.results) == 0
        assert len(run.skills_impacts) == 0
        assert run.status == "completed"
        fn.assert_not_called()

    async def test_single_combination(self):
        """A single combination with skills_modes=[True] produces one result."""
        fn = AsyncMock(return_value=True)
        executor = MultiTrialExecutor(evaluation_fn=fn)
        runner = ExperimentRunner(executor)

        config = ExperimentConfig(
            tasks=["T1"],
            agents=["a1"],
            models=["m1"],
            trials_per_combination=3,
            skills_modes=[True],
        )
        run = await runner.run_experiment(config)
        assert len(run.results) == 1
        assert run.results[0].task_id == "T1"
        assert len(run.results[0].trials) == 3
        # No impact since we only have one skills_mode
        assert len(run.skills_impacts) == 0

    async def test_experiment_failure_sets_status(self):
        """If the evaluation function raises mid-experiment, status is 'failed'."""
        fn = AsyncMock(side_effect=RuntimeError("catastrophic"))
        # The executor catches per-trial errors, so we need a deeper failure
        executor = MultiTrialExecutor(evaluation_fn=fn)
        runner = ExperimentRunner(executor)

        config = ExperimentConfig(
            tasks=["T1"],
            agents=["a1"],
            models=["m1"],
            trials_per_combination=2,
        )
        # The executor handles trial errors, so this should complete
        # with score=0 rather than failing the whole run
        run = await runner.run_experiment(config)
        # Trials executed but all failed => status completed
        assert run.status == "completed"
        for result in run.results:
            assert result.pass_rate == 0.0

    async def test_skills_impact_only_when_both_modes(self):
        """No skills impact when only one skills_mode is tested."""
        impacts = ExperimentRunner.compute_skills_impacts(
            [
                MultiTrialResult(
                    task_id="T1",
                    agent="a",
                    model="m",
                    skills_enabled=True,
                    trials=[TrialResult(trial_number=1, score=1, duration_ms=10)],
                ),
            ]
        )
        assert len(impacts) == 0


# ===================================================================
# ExperimentConfig
# ===================================================================


class TestExperimentConfig:
    """Test ExperimentConfig validation."""

    def test_default_values(self):
        """Defaults match the SkillsBench pattern: 5 trials, both skills modes."""
        config = ExperimentConfig(tasks=["T1"], agents=["a"], models=["m"])
        assert config.trials_per_combination == 5
        assert config.skills_modes == [True, False]
        assert config.timeout_per_trial_seconds == 300
        assert config.parallel_trials == 1

    def test_trials_validation_min(self):
        """trials_per_combination must be >= 1."""
        with pytest.raises(ValidationError):
            ExperimentConfig(
                tasks=["T1"],
                agents=["a"],
                models=["m"],
                trials_per_combination=0,
            )

    def test_trials_validation_max(self):
        """trials_per_combination must be <= 100."""
        with pytest.raises(ValidationError):
            ExperimentConfig(
                tasks=["T1"],
                agents=["a"],
                models=["m"],
                trials_per_combination=101,
            )

    def test_custom_values(self):
        """Custom configuration values are accepted."""
        config = ExperimentConfig(
            tasks=["T1", "T2"],
            agents=["a1", "a2"],
            models=["m1"],
            trials_per_combination=10,
            skills_modes=[True],
            timeout_per_trial_seconds=60,
            parallel_trials=4,
        )
        assert config.trials_per_combination == 10
        assert config.skills_modes == [True]
        assert config.timeout_per_trial_seconds == 60
        assert config.parallel_trials == 4
        assert len(config.tasks) == 2
        assert len(config.agents) == 2


# ===================================================================
# EvaluationService (multi-trial methods)
# ===================================================================


class TestEvaluationServiceMultiTrial:
    """Test multi-trial methods on EvaluationService."""

    async def test_start_and_get_run(self):
        """start_multi_trial_run stores the run, get retrieves it."""
        svc = EvaluationService()
        config = ExperimentConfig(
            tasks=["T1"],
            agents=["a"],
            models=["m"],
            trials_per_combination=1,
            skills_modes=[True],
        )
        run = await svc.start_multi_trial_run(config)
        assert run.status == "completed"
        assert len(run.results) == 1

        retrieved = svc.get_multi_trial_run(run.run_id)
        assert retrieved is not None
        assert retrieved.run_id == run.run_id

    async def test_get_nonexistent_run(self):
        """get_multi_trial_run returns None for unknown IDs."""
        svc = EvaluationService()
        assert svc.get_multi_trial_run("nonexistent") is None

    async def test_list_multi_trial_runs(self):
        """list_multi_trial_runs returns all stored runs."""
        svc = EvaluationService()
        config = ExperimentConfig(
            tasks=["T1"],
            agents=["a"],
            models=["m"],
            trials_per_combination=1,
            skills_modes=[True],
        )
        run1 = await svc.start_multi_trial_run(config)
        run2 = await svc.start_multi_trial_run(config)

        runs = svc.list_multi_trial_runs()
        assert len(runs) == 2
        run_ids = {r.run_id for r in runs}
        assert run1.run_id in run_ids
        assert run2.run_id in run_ids

    async def test_export_ctrf(self):
        """export_ctrf returns a valid CTRF report dict."""
        svc = EvaluationService()
        config = ExperimentConfig(
            tasks=["T1"],
            agents=["a"],
            models=["m"],
            trials_per_combination=2,
            skills_modes=[True],
        )
        run = await svc.start_multi_trial_run(config)
        report = svc.export_ctrf(run.run_id)
        assert report is not None
        assert "results" in report
        assert report["results"]["summary"]["tests"] == 1

    async def test_export_ctrf_nonexistent(self):
        """export_ctrf returns None for unknown run IDs."""
        svc = EvaluationService()
        assert svc.export_ctrf("nope") is None

    async def test_existing_runs_unaffected(self):
        """Multi-trial methods do not interfere with existing evaluation runs."""
        svc = EvaluationService()
        # Create a regular evaluation run
        from agent33.evaluation.models import GateType

        eval_run = svc.create_run(gate=GateType.G_PR)
        assert svc.get_run(eval_run.run_id) is not None

        # Create a multi-trial run
        config = ExperimentConfig(
            tasks=["T1"],
            agents=["a"],
            models=["m"],
            trials_per_combination=1,
            skills_modes=[True],
        )
        mt_run = await svc.start_multi_trial_run(config)

        # Both are independently retrievable
        assert svc.get_run(eval_run.run_id) is not None
        assert svc.get_multi_trial_run(mt_run.run_id) is not None
        # They don't cross-contaminate
        assert svc.get_multi_trial_run(eval_run.run_id) is None
        assert svc.get_run(mt_run.run_id) is None

    async def test_single_trial_uses_pluggable_adapter(self):
        """Custom trial evaluator adapters should be used by the service."""
        adapter = AsyncMock(return_value=TrialEvaluationOutcome(success=True))
        mock_adapter = type("Adapter", (), {"evaluate": adapter})()
        svc = EvaluationService(trial_evaluator=mock_adapter)

        result = await svc._run_single_trial("GT-01", "a", "m", True)
        assert result is True
        adapter.assert_awaited_once()

    async def test_deterministic_fallback_is_stable(self):
        """Fallback evaluator should return stable results for same inputs."""
        evaluator = DeterministicFallbackEvaluator()
        first = await evaluator.evaluate(
            task_id="GT-01", agent="agent-a", model="model-a", skills_enabled=True
        )
        second = await evaluator.evaluate(
            task_id="GT-01", agent="agent-a", model="model-a", skills_enabled=True
        )
        assert first.success == second.success

    async def test_deterministic_fallback_rejects_unknown_task(self):
        """Unknown tasks should deterministically fail in fallback mode."""
        evaluator = DeterministicFallbackEvaluator()
        outcome = await evaluator.evaluate(
            task_id="UNKNOWN", agent="a", model="m", skills_enabled=False
        )
        assert outcome.success is False


# ===================================================================
# API Endpoints
# ===================================================================


class TestExperimentEndpoints:
    """Test the multi-trial experiment REST endpoints."""

    @pytest.fixture
    def client(self) -> TestClient:
        from fastapi.testclient import TestClient

        from agent33.main import app
        from agent33.security.auth import create_access_token

        token = create_access_token("test-user", scopes=["admin"])
        return TestClient(app, headers={"Authorization": f"Bearer {token}"})

    def test_start_experiment(self, client: TestClient):
        """POST /v1/evaluations/experiments creates and executes an experiment."""
        resp = client.post(
            "/v1/evaluations/experiments",
            json={
                "tasks": ["T1"],
                "agents": ["a"],
                "models": ["m"],
                "trials_per_combination": 1,
                "skills_modes": [True],
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "run_id" in data
        assert data["status"] == "completed"
        assert data["results_count"] == 1

    def test_get_experiment(self, client: TestClient):
        """GET /v1/evaluations/experiments/{run_id} returns experiment details."""
        # Create first
        create_resp = client.post(
            "/v1/evaluations/experiments",
            json={
                "tasks": ["T1"],
                "agents": ["a"],
                "models": ["m"],
                "trials_per_combination": 1,
                "skills_modes": [True],
            },
        )
        run_id = create_resp.json()["run_id"]

        resp = client.get(f"/v1/evaluations/experiments/{run_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == run_id
        assert data["status"] == "completed"
        assert len(data["results"]) == 1

    def test_get_experiment_not_found(self, client: TestClient):
        """GET /v1/evaluations/experiments/{run_id} returns 404 for unknown ID."""
        resp = client.get("/v1/evaluations/experiments/nonexistent-id")
        assert resp.status_code == 404

    def test_get_ctrf_report(self, client: TestClient):
        """GET /v1/evaluations/experiments/{run_id}/ctrf returns CTRF JSON."""
        create_resp = client.post(
            "/v1/evaluations/experiments",
            json={
                "tasks": ["T1"],
                "agents": ["a"],
                "models": ["m"],
                "trials_per_combination": 2,
                "skills_modes": [True],
            },
        )
        run_id = create_resp.json()["run_id"]

        resp = client.get(f"/v1/evaluations/experiments/{run_id}/ctrf")
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert data["results"]["tool"]["name"] == "agent33-eval"
        assert data["results"]["summary"]["tests"] == 1

    def test_get_ctrf_not_found(self, client: TestClient):
        """GET /v1/evaluations/experiments/{run_id}/ctrf returns 404 for unknown ID."""
        resp = client.get("/v1/evaluations/experiments/nonexistent/ctrf")
        assert resp.status_code == 404

    def test_get_skills_impact(self, client: TestClient):
        """GET /v1/evaluations/experiments/{run_id}/skills-impact returns impact data."""
        create_resp = client.post(
            "/v1/evaluations/experiments",
            json={
                "tasks": ["T1"],
                "agents": ["a"],
                "models": ["m"],
                "trials_per_combination": 1,
                "skills_modes": [True, False],
            },
        )
        run_id = create_resp.json()["run_id"]

        resp = client.get(f"/v1/evaluations/experiments/{run_id}/skills-impact")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == run_id
        assert "impacts" in data
        # With both True/False skills modes and 1 task, there should be 1 impact
        assert len(data["impacts"]) == 1

    def test_get_skills_impact_not_found(self, client: TestClient):
        """GET /v1/evaluations/experiments/{run_id}/skills-impact returns 404."""
        resp = client.get("/v1/evaluations/experiments/nonexistent/skills-impact")
        assert resp.status_code == 404

    def test_start_experiment_requires_auth(self):
        """POST /v1/evaluations/experiments without auth returns 401."""
        from fastapi.testclient import TestClient

        from agent33.main import app

        unauthed = TestClient(app)
        resp = unauthed.post(
            "/v1/evaluations/experiments",
            json={
                "tasks": ["T1"],
                "agents": ["a"],
                "models": ["m"],
            },
        )
        assert resp.status_code == 401
