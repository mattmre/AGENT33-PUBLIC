"""P4.11 -- LLM Evaluator Integration Testing.

Tests that validate the full evaluation pipeline with realistic LLM responses,
covering:
- LLM evaluator producing numeric scores from structured JSON output
- Gate enforcement using realistic score values
- Multi-criteria evaluation flow
- Config-driven judge model selection
- Error handling at the pipeline level (malformed responses, timeouts)
- Integration between LLMEvaluator, EvaluationService, and GateEnforcer

These tests use mocks that return **realistic** LLM responses (structured JSON
with scores, reasoning, criteria), not the shallow mocks from P2.2 that return
trivial pass/fail. The realistic mocks simulate what a real LLM would return.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent33.evaluation.evaluator_interface import (
    EvaluationInput,
    EvaluationResult,
    EvaluationVerdict,
)
from agent33.evaluation.evaluator_registry import (
    EvaluatorRegistry,
    register_llm_evaluator,
)
from agent33.evaluation.gates import GateEnforcer
from agent33.evaluation.llm_evaluator import LLMEvaluator
from agent33.evaluation.metrics import MetricsCalculator
from agent33.evaluation.models import (
    GateResult,
    GateType,
    MetricId,
    TaskResult,
    TaskRunResult,
)
from agent33.evaluation.service import EvaluationService

# -------------------------------------------------------------------------
# Realistic LLM response fixtures
# -------------------------------------------------------------------------

REALISTIC_PASS_RESPONSE: dict[str, object] = {
    "verdict": "pass",
    "score": 0.85,
    "reason": (
        "The response covers the key aspects of the question accurately. "
        "The implementation is functionally correct and handles basic edge cases. "
        "Minor style issues noted but do not affect correctness."
    ),
}

REALISTIC_FAIL_RESPONSE: dict[str, object] = {
    "verdict": "fail",
    "score": 0.35,
    "reason": (
        "The response misses the core requirement. The expected output demands "
        "a recursive implementation, but a simple loop was used instead. "
        "Additionally, no error handling is present for negative inputs."
    ),
}

REALISTIC_PARTIAL_PASS_RESPONSE: dict[str, object] = {
    "verdict": "pass",
    "score": 0.72,
    "reason": (
        "Output is mostly correct. The primary logic is sound and produces "
        "the right result for standard inputs. However, the edge case handling "
        "for empty collections is missing, bringing the score down."
    ),
}

REALISTIC_HIGH_CONFIDENCE_PASS: dict[str, object] = {
    "verdict": "pass",
    "score": 0.98,
    "reason": (
        "Exact match with expected output. All test criteria satisfied. "
        "Implementation follows best practices with proper type annotations "
        "and docstrings."
    ),
}

REALISTIC_BORDERLINE_FAIL: dict[str, object] = {
    "verdict": "fail",
    "score": 0.65,
    "reason": (
        "The implementation is close but has a subtle off-by-one error in "
        "the boundary condition. The overall structure is correct but the "
        "bug in line 15 causes incorrect output for inputs at the boundary."
    ),
}

MALFORMED_RESPONSES: list[str] = [
    "This is just text, not JSON at all",
    '{"partial": json is broken here',
    '{"score": "not a number", "verdict": "pass", "reason": "ok"}',
    "",
    '{"verdict": 42, "score": 0.5, "reason": "numeric verdict"}',
]


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------


def _make_router(
    response_json: dict[str, object] | None = None,
    *,
    response_text: str | None = None,
    raise_exc: Exception | None = None,
) -> MagicMock:
    """Build a mock ModelRouter that returns a realistic LLM response."""
    router = MagicMock()
    if raise_exc is not None:
        router.complete = AsyncMock(side_effect=raise_exc)
    else:
        if response_text is not None:
            payload = response_text
        else:
            payload = json.dumps(response_json or REALISTIC_PASS_RESPONSE)
        mock_response = MagicMock()
        mock_response.content = payload
        router.complete = AsyncMock(return_value=mock_response)
    return router


def _make_router_sequence(response_jsons: list[dict[str, object]]) -> MagicMock:
    """Build a mock router that returns a sequence of JSON responses."""
    router = MagicMock()
    mock_resps = []
    for resp_json in response_jsons:
        resp = MagicMock()
        resp.content = json.dumps(resp_json)
        mock_resps.append(resp)
    router.complete = AsyncMock(side_effect=mock_resps)
    return router


def _make_input(
    *,
    task_id: str = "int-t1",
    prompt: str = "Implement binary search",
    actual: str = "def binary_search(arr, target): ...",
    expected: str | None = "A correct binary search implementation",
) -> EvaluationInput:
    return EvaluationInput(
        task_id=task_id,
        prompt=prompt,
        actual_output=actual,
        expected_output=expected,
    )


# =========================================================================
# TestLLMEvaluatorWithRealisticProvider
# =========================================================================


class TestLLMEvaluatorWithRealisticProvider:
    """Tests that validate the full evaluation pipeline with realistic LLM responses.

    These use mock routers that return the kind of structured JSON an actual
    LLM judge would produce -- complete with detailed reasoning, precise
    numeric scores, and multi-criteria considerations.
    """

    async def test_evaluation_produces_numeric_scores(self) -> None:
        """LLM evaluator produces valid numeric scores from structured LLM output."""
        router = _make_router(REALISTIC_PASS_RESPONSE)
        ev = LLMEvaluator(model_router=router, model="gpt-4o-mini")
        result = await ev.evaluate(_make_input())

        assert result.verdict == EvaluationVerdict.PASS
        assert result.score == pytest.approx(0.85)
        assert isinstance(result.score, float)
        assert 0.0 <= result.score <= 1.0
        assert "key aspects" in result.reason
        assert result.evaluator_id == "llm_judge_v1"
        assert result.task_id == "int-t1"

    async def test_evaluation_produces_fail_with_detailed_reason(self) -> None:
        """LLM evaluator correctly parses a detailed FAIL response."""
        router = _make_router(REALISTIC_FAIL_RESPONSE)
        ev = LLMEvaluator(model_router=router, model="gpt-4o-mini")
        result = await ev.evaluate(
            _make_input(
                task_id="fail-detailed",
                actual="def search(arr): return arr[0]",
                expected="A recursive binary search",
            )
        )

        assert result.verdict == EvaluationVerdict.FAIL
        assert result.score == pytest.approx(0.35)
        assert "recursive" in result.reason.lower()
        assert "error handling" in result.reason.lower()

    async def test_borderline_score_preserves_verdict(self) -> None:
        """A borderline score (0.65) with FAIL verdict is preserved correctly."""
        router = _make_router(REALISTIC_BORDERLINE_FAIL)
        ev = LLMEvaluator(model_router=router, model="judge-v2")
        result = await ev.evaluate(_make_input(task_id="borderline-1"))

        assert result.verdict == EvaluationVerdict.FAIL
        assert result.score == pytest.approx(0.65)
        assert "off-by-one" in result.reason.lower()

    async def test_high_confidence_pass(self) -> None:
        """A high-confidence pass (0.98) flows through correctly."""
        router = _make_router(REALISTIC_HIGH_CONFIDENCE_PASS)
        ev = LLMEvaluator(model_router=router, model="gpt-4o")
        result = await ev.evaluate(_make_input(task_id="high-conf-1"))

        assert result.verdict == EvaluationVerdict.PASS
        assert result.score == pytest.approx(0.98)
        assert "exact match" in result.reason.lower()

    async def test_evaluation_handles_malformed_llm_response_text(self) -> None:
        """Evaluator gracefully handles LLM returning plain text instead of JSON."""
        router = _make_router(response_text="This is just text, not JSON at all")
        ev = LLMEvaluator(model_router=router, model="m")
        result = await ev.evaluate(_make_input(task_id="malformed-text"))

        assert result.verdict == EvaluationVerdict.ERROR
        assert result.score == 0.0
        assert result.task_id == "malformed-text"
        # The reason should explain the parse failure
        assert "json" in result.reason.lower() or "parse" in result.reason.lower()

    async def test_evaluation_handles_partial_json(self) -> None:
        """Evaluator gracefully handles truncated/partial JSON."""
        router = _make_router(response_text='{"partial": json is broken here')
        ev = LLMEvaluator(model_router=router, model="m")
        result = await ev.evaluate(_make_input(task_id="malformed-partial"))

        assert result.verdict == EvaluationVerdict.ERROR
        assert result.score == 0.0

    async def test_evaluation_handles_non_numeric_score(self) -> None:
        """Evaluator handles LLM returning a non-numeric score string."""
        router = _make_router(
            response_text='{"score": "not a number", "verdict": "pass", "reason": "ok"}'
        )
        ev = LLMEvaluator(model_router=router, model="m")
        result = await ev.evaluate(_make_input(task_id="malformed-score"))

        # float("not a number") raises ValueError, which is caught
        assert result.verdict == EvaluationVerdict.ERROR
        assert result.score == 0.0

    async def test_evaluation_handles_empty_response(self) -> None:
        """Evaluator handles completely empty LLM response."""
        router = _make_router(response_text="")
        ev = LLMEvaluator(model_router=router, model="m")
        result = await ev.evaluate(_make_input(task_id="malformed-empty"))

        assert result.verdict == EvaluationVerdict.ERROR
        assert result.score == 0.0

    async def test_evaluation_handles_llm_timeout(self) -> None:
        """Evaluator handles provider timeout gracefully."""
        router = _make_router(raise_exc=TimeoutError("LLM request timed out after 30s"))
        ev = LLMEvaluator(model_router=router, model="gpt-4o-mini")
        result = await ev.evaluate(_make_input(task_id="timeout-1"))

        assert result.verdict == EvaluationVerdict.ERROR
        assert result.score == 0.0
        assert "timed out" in result.reason.lower()
        assert result.task_id == "timeout-1"
        assert result.evaluator_id == "llm_judge_v1"

    async def test_evaluation_handles_connection_refused(self) -> None:
        """Evaluator handles connection refused (e.g. Ollama not running)."""
        router = _make_router(raise_exc=ConnectionError("Connection refused"))
        ev = LLMEvaluator(model_router=router, model="llama3.2")
        result = await ev.evaluate(_make_input(task_id="conn-refused-1"))

        assert result.verdict == EvaluationVerdict.ERROR
        assert "connection" in result.reason.lower()

    async def test_evaluation_with_multiple_criteria_in_reasoning(self) -> None:
        """Evaluator can process multi-criteria reasoning in single evaluation.

        Simulates a real LLM judge that considers accuracy, completeness,
        and clarity in its reasoning.
        """
        multi_criteria_response = {
            "verdict": "pass",
            "score": 0.78,
            "reason": (
                "Accuracy: 90/100 - Core algorithm is correct. "
                "Completeness: 70/100 - Missing edge case for empty input. "
                "Clarity: 75/100 - Variable names are acceptable but could be more descriptive. "
                "Overall weighted score reflects these individual assessments."
            ),
        }
        router = _make_router(multi_criteria_response)
        ev = LLMEvaluator(model_router=router, model="gpt-4o")
        result = await ev.evaluate(
            _make_input(
                task_id="multi-criteria-1",
                prompt="Implement a well-documented sort function",
                actual="def sort(arr): return sorted(arr)",
                expected="A clear, well-documented sorting function with edge case handling",
            )
        )

        assert result.verdict == EvaluationVerdict.PASS
        assert result.score == pytest.approx(0.78)
        assert "accuracy" in result.reason.lower()
        assert "completeness" in result.reason.lower()
        assert "clarity" in result.reason.lower()

    async def test_evaluation_respects_judge_model_config(self) -> None:
        """When evaluation_judge_model is set, that model is used for evaluation."""
        router = _make_router(REALISTIC_PASS_RESPONSE)
        judge_model = "gpt-4o-mini"
        ev = LLMEvaluator(model_router=router, model=judge_model)
        await ev.evaluate(_make_input())

        router.complete.assert_called_once()
        _, kwargs = router.complete.call_args
        assert kwargs["model"] == judge_model

    async def test_evaluation_uses_different_judge_model(self) -> None:
        """Different judge model identifiers are forwarded correctly."""
        router = _make_router(REALISTIC_PASS_RESPONSE)
        ev = LLMEvaluator(model_router=router, model="claude-3-haiku-20240307")
        await ev.evaluate(_make_input())

        _, kwargs = router.complete.call_args
        assert kwargs["model"] == "claude-3-haiku-20240307"

    async def test_batch_evaluation_with_realistic_responses(self) -> None:
        """Batch of evaluations with varied realistic responses."""
        responses = [
            REALISTIC_HIGH_CONFIDENCE_PASS,
            REALISTIC_FAIL_RESPONSE,
            REALISTIC_PARTIAL_PASS_RESPONSE,
            REALISTIC_BORDERLINE_FAIL,
        ]
        router = _make_router_sequence(responses)
        ev = LLMEvaluator(model_router=router, model="gpt-4o")

        inputs = [
            _make_input(task_id="batch-1", actual="perfect answer", expected="perfect answer"),
            _make_input(task_id="batch-2", actual="wrong", expected="right"),
            _make_input(task_id="batch-3", actual="mostly ok", expected="fully correct"),
            _make_input(task_id="batch-4", actual="close but buggy", expected="correct"),
        ]
        results = await ev.evaluate_batch(inputs)

        assert len(results) == 4
        assert results[0].verdict == EvaluationVerdict.PASS
        assert results[0].score == pytest.approx(0.98)
        assert results[1].verdict == EvaluationVerdict.FAIL
        assert results[1].score == pytest.approx(0.35)
        assert results[2].verdict == EvaluationVerdict.PASS
        assert results[2].score == pytest.approx(0.72)
        assert results[3].verdict == EvaluationVerdict.FAIL
        assert results[3].score == pytest.approx(0.65)


# =========================================================================
# TestGateEnforcementWithRealisticScores
# =========================================================================


class TestGateEnforcementWithRealisticScores:
    """Tests that gate enforcement works correctly with realistic evaluation scores.

    Validates the full pipeline: LLM response -> EvaluationService metrics ->
    GateEnforcer check.
    """

    def _build_task_results(
        self,
        pass_count: int,
        fail_count: int,
        *,
        duration_ms: int = 150,
    ) -> list[TaskRunResult]:
        """Build a list of TaskRunResult with the given pass/fail counts."""
        results: list[TaskRunResult] = []
        for i in range(pass_count):
            results.append(
                TaskRunResult(
                    item_id=f"GT-{i + 1:02d}",
                    result=TaskResult.PASS,
                    checks_passed=3,
                    checks_total=3,
                    duration_ms=duration_ms,
                )
            )
        for i in range(fail_count):
            results.append(
                TaskRunResult(
                    item_id=f"GT-F{i + 1:02d}",
                    result=TaskResult.FAIL,
                    checks_passed=1,
                    checks_total=3,
                    duration_ms=duration_ms,
                )
            )
        return results

    def test_pr_gate_passes_with_high_success_rate(self) -> None:
        """G-PR gate passes when success rate >= 80%."""
        calculator = MetricsCalculator()
        enforcer = GateEnforcer()

        # 9 pass, 1 fail = 90% success rate, exceeds G-PR threshold of 80%
        task_results = self._build_task_results(9, 1)
        metrics = calculator.compute_all(task_results, rework_count=0, scope_violations=0)
        metric_values = {m.metric_id: m.value for m in metrics}

        report = enforcer.check_gate(GateType.G_PR, metric_values, task_results)
        assert report.overall == GateResult.PASS

    def test_pr_gate_fails_with_low_success_rate(self) -> None:
        """G-PR gate fails when success rate < 80%."""
        calculator = MetricsCalculator()
        enforcer = GateEnforcer()

        # 7 pass, 3 fail = 70% success rate, below G-PR threshold of 80%
        task_results = self._build_task_results(7, 3)
        metrics = calculator.compute_all(task_results, rework_count=0, scope_violations=0)
        metric_values = {m.metric_id: m.value for m in metrics}

        report = enforcer.check_gate(GateType.G_PR, metric_values, task_results)
        assert report.overall == GateResult.FAIL

    def test_merge_gate_requires_higher_success_rate(self) -> None:
        """G-MRG gate requires >= 90% success rate (stricter than G-PR)."""
        calculator = MetricsCalculator()
        enforcer = GateEnforcer()

        # 85% success -- passes G-PR but fails G-MRG
        task_results = self._build_task_results(17, 3)
        metrics = calculator.compute_all(task_results, rework_count=0, scope_violations=0)
        metric_values = {m.metric_id: m.value for m in metrics}

        pr_report = enforcer.check_gate(GateType.G_PR, metric_values, task_results)
        mrg_report = enforcer.check_gate(GateType.G_MRG, metric_values, task_results)

        assert pr_report.overall == GateResult.PASS
        assert mrg_report.overall == GateResult.FAIL

    def test_release_gate_is_strictest(self) -> None:
        """G-REL gate requires >= 95% success rate."""
        calculator = MetricsCalculator()
        enforcer = GateEnforcer()

        # 92% -- passes G-PR and G-MRG but fails G-REL
        task_results = self._build_task_results(92, 8)
        metrics = calculator.compute_all(task_results, rework_count=0, scope_violations=0)
        metric_values = {m.metric_id: m.value for m in metrics}

        pr_report = enforcer.check_gate(GateType.G_PR, metric_values, task_results)
        rel_report = enforcer.check_gate(GateType.G_REL, metric_values, task_results)

        assert pr_report.overall == GateResult.PASS
        assert rel_report.overall == GateResult.FAIL

    def test_gate_with_rework_rate_penalty(self) -> None:
        """Gate considers rework rate in addition to success rate."""
        calculator = MetricsCalculator()
        enforcer = GateEnforcer()

        # 95% success rate, but 25% rework rate
        task_results = self._build_task_results(19, 1)
        metrics = calculator.compute_all(task_results, rework_count=5, scope_violations=0)
        metric_values = {m.metric_id: m.value for m in metrics}

        # G-MRG blocks on rework_rate > 20%
        mrg_report = enforcer.check_gate(GateType.G_MRG, metric_values, task_results)
        assert mrg_report.overall == GateResult.FAIL

        # Check that the specific rework check failed
        rework_checks = [
            c for c in mrg_report.check_results if c.threshold.metric_id == MetricId.M_03
        ]
        assert len(rework_checks) == 1
        assert not rework_checks[0].passed
        assert rework_checks[0].actual_value == pytest.approx(25.0)

    def test_gate_with_scope_adherence_failure(self) -> None:
        """Gate checks scope adherence (M-05) enforcement."""
        calculator = MetricsCalculator()
        enforcer = GateEnforcer()

        # 100% success rate but 15% scope violations -> 85% adherence
        task_results = self._build_task_results(20, 0)
        metrics = calculator.compute_all(task_results, rework_count=0, scope_violations=3)
        metric_values = {m.metric_id: m.value for m in metrics}

        # G-PR requires scope adherence >= 90%
        pr_report = enforcer.check_gate(GateType.G_PR, metric_values, task_results)
        assert pr_report.overall == GateResult.FAIL

        scope_checks = [
            c for c in pr_report.check_results if c.threshold.metric_id == MetricId.M_05
        ]
        assert len(scope_checks) == 1
        assert not scope_checks[0].passed
        assert scope_checks[0].actual_value == pytest.approx(85.0)


# =========================================================================
# TestEvaluationServicePipelineIntegration
# =========================================================================


class TestEvaluationServicePipelineIntegration:
    """Tests that validate the full EvaluationService pipeline with realistic data.

    Verifies that creating a run, submitting results, computing metrics,
    and checking gates all work together correctly.
    """

    def test_full_pipeline_pass(self) -> None:
        """Full pipeline: create run -> submit results -> gate PASS."""
        service = EvaluationService()
        run = service.create_run(GateType.G_PR, commit_hash="abc123", branch="feature/test")

        assert run.run_id.startswith("EVAL-")
        assert run.gate == GateType.G_PR
        assert run.completed_at is None

        # 9/10 tasks pass = 90% success rate, exceeds G-PR 80% threshold
        task_results = [
            TaskRunResult(
                item_id=f"GT-{i + 1:02d}",
                result=TaskResult.PASS,
                checks_passed=3,
                checks_total=3,
                duration_ms=120,
            )
            for i in range(9)
        ] + [
            TaskRunResult(
                item_id="GT-10",
                result=TaskResult.FAIL,
                checks_passed=1,
                checks_total=3,
                duration_ms=200,
            )
        ]

        completed = service.submit_results(run.run_id, task_results)
        assert completed is not None
        assert completed.completed_at is not None
        assert completed.gate_report is not None
        assert completed.gate_report.overall == GateResult.PASS
        assert len(completed.metrics) == 5  # M-01 through M-05

        # Verify individual metric values
        metric_map = {m.metric_id: m.value for m in completed.metrics}
        assert metric_map[MetricId.M_01] == pytest.approx(90.0)  # 90% success
        assert metric_map[MetricId.M_03] == pytest.approx(0.0)  # 0% rework
        assert metric_map[MetricId.M_05] == pytest.approx(100.0)  # 100% scope adherence

    def test_full_pipeline_fail(self) -> None:
        """Full pipeline: gate FAIL when metrics below threshold."""
        service = EvaluationService()
        run = service.create_run(GateType.G_MRG)

        # 8/10 tasks pass = 80%, below G-MRG 90% threshold
        task_results = [
            TaskRunResult(
                item_id=f"GT-{i + 1:02d}",
                result=TaskResult.PASS if i < 8 else TaskResult.FAIL,
                checks_passed=3 if i < 8 else 0,
                checks_total=3,
                duration_ms=100,
            )
            for i in range(10)
        ]

        completed = service.submit_results(run.run_id, task_results)
        assert completed is not None
        assert completed.gate_report is not None
        # G-MRG blocks on failed golden tasks for merge/release gates
        assert completed.gate_report.overall == GateResult.FAIL

    def test_pipeline_with_baseline_and_no_regressions(self) -> None:
        """Pipeline saves baseline and detects no regressions on equal run."""
        service = EvaluationService()

        # First run: establish baseline
        run1 = service.create_run(GateType.G_PR)
        results1 = [
            TaskRunResult(
                item_id=f"GT-{i + 1:02d}",
                result=TaskResult.PASS,
                checks_passed=3,
                checks_total=3,
                duration_ms=100,
            )
            for i in range(10)
        ]
        completed1 = service.submit_results(run1.run_id, results1)
        assert completed1 is not None

        # Save baseline from first run
        baseline = service.save_baseline(completed1.metrics, results1, commit_hash="baseline-hash")
        assert baseline.baseline_id.startswith("BSL-")

        # Second run: same results -- no regressions expected
        run2 = service.create_run(GateType.G_PR)
        completed2 = service.submit_results(run2.run_id, results1)
        assert completed2 is not None
        assert completed2.gate_report is not None
        assert completed2.gate_report.overall == GateResult.PASS
        # No regressions when metrics are equal to baseline
        assert len(completed2.regressions) == 0

    def test_run_not_found_returns_none(self) -> None:
        """submit_results returns None for unknown run ID."""
        service = EvaluationService()
        result = service.submit_results("nonexistent-run-id", [])
        assert result is None

    def test_multiple_concurrent_runs(self) -> None:
        """Service handles multiple concurrent evaluation runs."""
        service = EvaluationService()
        run_pr = service.create_run(GateType.G_PR, branch="feature/a")
        run_mrg = service.create_run(GateType.G_MRG, branch="main")

        all_pass = [
            TaskRunResult(
                item_id=f"GT-{i + 1:02d}",
                result=TaskResult.PASS,
                checks_passed=3,
                checks_total=3,
                duration_ms=100,
            )
            for i in range(10)
        ]

        # Submit to both runs
        completed_pr = service.submit_results(run_pr.run_id, all_pass)
        completed_mrg = service.submit_results(run_mrg.run_id, all_pass)

        assert completed_pr is not None
        assert completed_mrg is not None
        assert completed_pr.run_id != completed_mrg.run_id
        assert completed_pr.gate_report is not None
        assert completed_mrg.gate_report is not None
        assert completed_pr.gate_report.overall == GateResult.PASS
        assert completed_mrg.gate_report.overall == GateResult.PASS

        # Verify runs are listed
        runs = service.list_runs()
        assert len(runs) == 2


# =========================================================================
# TestLLMEvaluatorToGatePipeline
# =========================================================================


class TestLLMEvaluatorToGatePipeline:
    """End-to-end tests: LLM evaluator produces scores that drive gate decisions.

    This bridges the gap between the LLM evaluator (which produces
    EvaluationResult with score/verdict) and the gate enforcer (which checks
    MetricValues against thresholds).
    """

    async def test_llm_scores_converted_to_task_results_for_gate(self) -> None:
        """LLM evaluation verdicts can be mapped to TaskRunResults for gate checking."""
        # Simulate a batch of LLM evaluations
        responses = [
            {"verdict": "pass", "score": 0.92, "reason": "Correct"},
            {"verdict": "pass", "score": 0.88, "reason": "Good"},
            {"verdict": "pass", "score": 0.95, "reason": "Excellent"},
            {"verdict": "fail", "score": 0.40, "reason": "Wrong approach"},
            {"verdict": "pass", "score": 0.75, "reason": "Acceptable"},
        ]
        router = _make_router_sequence(responses)
        ev = LLMEvaluator(model_router=router, model="gpt-4o-mini")

        inputs = [_make_input(task_id=f"gate-t{i}") for i in range(5)]
        eval_results = await ev.evaluate_batch(inputs)

        # Convert LLM results to TaskRunResults
        task_results = []
        for er in eval_results:
            is_pass = er.verdict == EvaluationVerdict.PASS
            tr_result = TaskResult.PASS if is_pass else TaskResult.FAIL
            task_results.append(
                TaskRunResult(
                    item_id=er.task_id,
                    result=tr_result,
                    checks_passed=1 if er.verdict == EvaluationVerdict.PASS else 0,
                    checks_total=1,
                    duration_ms=100,
                )
            )

        # Run through gate enforcement
        calculator = MetricsCalculator()
        metrics = calculator.compute_all(task_results)
        metric_values = {m.metric_id: m.value for m in metrics}

        enforcer = GateEnforcer()
        report = enforcer.check_gate(GateType.G_PR, metric_values, task_results)

        # 4/5 pass = 80%, exactly at G-PR threshold
        assert metric_values[MetricId.M_01] == pytest.approx(80.0)
        assert report.overall == GateResult.PASS

    async def test_all_llm_failures_block_merge_gate(self) -> None:
        """When all LLM evaluations fail, the merge gate is blocked."""
        responses = [REALISTIC_FAIL_RESPONSE] * 5
        router = _make_router_sequence(responses)
        ev = LLMEvaluator(model_router=router, model="gpt-4o-mini")

        inputs = [_make_input(task_id=f"all-fail-{i}") for i in range(5)]
        eval_results = await ev.evaluate_batch(inputs)

        task_results = [
            TaskRunResult(
                item_id=er.task_id,
                result=TaskResult.FAIL,
                checks_passed=0,
                checks_total=1,
                duration_ms=100,
            )
            for er in eval_results
        ]

        calculator = MetricsCalculator()
        metrics = calculator.compute_all(task_results)
        metric_values = {m.metric_id: m.value for m in metrics}

        enforcer = GateEnforcer()
        report = enforcer.check_gate(GateType.G_MRG, metric_values, task_results)

        assert metric_values[MetricId.M_01] == pytest.approx(0.0)
        assert report.overall == GateResult.FAIL

    async def test_llm_errors_treated_as_failures_in_gate(self) -> None:
        """LLM provider errors are treated as task failures in gate checks."""
        router = _make_router(raise_exc=RuntimeError("Provider unavailable"))
        ev = LLMEvaluator(model_router=router, model="m")

        inputs = [_make_input(task_id=f"err-{i}") for i in range(3)]
        eval_results = await ev.evaluate_batch(inputs)

        # All should be ERROR verdict
        assert all(r.verdict == EvaluationVerdict.ERROR for r in eval_results)

        # Map ERROR to FAIL for gate purposes
        task_results = [
            TaskRunResult(
                item_id=er.task_id,
                result=TaskResult.FAIL,
                checks_passed=0,
                checks_total=1,
                duration_ms=0,
            )
            for er in eval_results
        ]

        calculator = MetricsCalculator()
        metrics = calculator.compute_all(task_results)
        metric_values = {m.metric_id: m.value for m in metrics}

        enforcer = GateEnforcer()
        report = enforcer.check_gate(GateType.G_PR, metric_values, task_results)

        assert metric_values[MetricId.M_01] == pytest.approx(0.0)
        assert report.overall == GateResult.FAIL


# =========================================================================
# TestConfigValidation
# =========================================================================


class TestConfigValidation:
    """Tests that validate evaluation_judge_model configuration behavior."""

    def test_default_judge_model_is_empty(self) -> None:
        """Default evaluation_judge_model is empty string (LLM evaluator disabled)."""
        from agent33.config import Settings

        s = Settings()
        assert s.evaluation_judge_model == ""

    def test_judge_model_can_be_set(self) -> None:
        """evaluation_judge_model accepts valid model identifiers."""
        from agent33.config import Settings

        s = Settings(evaluation_judge_model="gpt-4o-mini")
        assert s.evaluation_judge_model == "gpt-4o-mini"

    def test_judge_model_ollama(self) -> None:
        """evaluation_judge_model accepts Ollama model identifiers."""
        from agent33.config import Settings

        s = Settings(evaluation_judge_model="llama3.2")
        assert s.evaluation_judge_model == "llama3.2"

    def test_empty_model_prevents_evaluator_construction(self) -> None:
        """LLMEvaluator refuses construction with empty model string."""
        router = MagicMock()
        with pytest.raises(ValueError, match="non-empty"):
            LLMEvaluator(model_router=router, model="")

    def test_register_llm_evaluator_with_configured_model(self) -> None:
        """register_llm_evaluator wires model from config into evaluator."""
        router = _make_router()
        registry = EvaluatorRegistry()
        model = "gpt-4o-mini"
        ev = register_llm_evaluator(registry, router, model)

        assert ev.evaluator_id == "llm_judge_v1"
        assert registry.get("llm_judge_v1") is ev

    def test_model_router_route_fails_for_unknown_model(self) -> None:
        """ModelRouter raises ValueError for unknown model with no default provider."""
        from agent33.llm.router import ModelRouter

        router = ModelRouter(providers={}, default_provider="ollama")
        with pytest.raises(ValueError, match="No provider found"):
            router.route("unknown-model-xyz")

    def test_model_router_routes_openai_prefixed_models(self) -> None:
        """ModelRouter routes gpt- prefixed models to 'openai' provider."""
        from agent33.llm.router import ModelRouter

        mock_provider = MagicMock()
        router = ModelRouter(providers={"openai": mock_provider})
        provider = router.route("gpt-4o-mini")
        assert provider is mock_provider

    def test_model_router_routes_ollama_as_default(self) -> None:
        """ModelRouter routes non-prefixed models to default 'ollama' provider."""
        from agent33.llm.router import ModelRouter

        mock_provider = MagicMock()
        router = ModelRouter(providers={"ollama": mock_provider})
        provider = router.route("llama3.2")
        assert provider is mock_provider


# =========================================================================
# TestEvaluationConfigValidation
# =========================================================================


class TestEvaluationConfigValidation:
    """Tests for the evaluation.validation module (P4.11)."""

    def test_check_configured_returns_false_for_empty(self) -> None:
        """check_judge_model_configured returns False when model is empty."""
        from agent33.config import Settings
        from agent33.evaluation.validation import check_judge_model_configured

        s = Settings(evaluation_judge_model="")
        assert check_judge_model_configured(s) is False

    def test_check_configured_returns_true_for_set_model(self) -> None:
        """check_judge_model_configured returns True when model is set."""
        from agent33.config import Settings
        from agent33.evaluation.validation import check_judge_model_configured

        s = Settings(evaluation_judge_model="gpt-4o-mini")
        assert check_judge_model_configured(s) is True

    def test_check_configured_strips_whitespace(self) -> None:
        """check_judge_model_configured treats whitespace-only as empty."""
        from agent33.config import Settings
        from agent33.evaluation.validation import check_judge_model_configured

        s = Settings(evaluation_judge_model="   ")
        assert check_judge_model_configured(s) is False

    def test_check_available_returns_true_when_routable(self) -> None:
        """check_judge_model_available returns True when router can route the model."""
        from agent33.config import Settings
        from agent33.evaluation.validation import check_judge_model_available
        from agent33.llm.router import ModelRouter

        s = Settings(evaluation_judge_model="gpt-4o-mini")
        mock_provider = MagicMock()
        router = ModelRouter(providers={"openai": mock_provider})
        assert check_judge_model_available(s, router) is True

    def test_check_available_returns_false_when_not_routable(self) -> None:
        """check_judge_model_available returns False when no provider can serve model."""
        from agent33.config import Settings
        from agent33.evaluation.validation import check_judge_model_available
        from agent33.llm.router import ModelRouter

        s = Settings(evaluation_judge_model="gpt-4o-mini")
        router = ModelRouter(providers={}, default_provider="none")
        assert check_judge_model_available(s, router) is False

    def test_check_available_returns_false_for_empty_model(self) -> None:
        """check_judge_model_available returns False when model is empty."""
        from agent33.config import Settings
        from agent33.evaluation.validation import check_judge_model_available
        from agent33.llm.router import ModelRouter

        s = Settings(evaluation_judge_model="")
        router = ModelRouter()
        assert check_judge_model_available(s, router) is False

    def test_validate_returns_empty_when_valid(self) -> None:
        """validate_evaluation_config returns no warnings when config is valid."""
        from agent33.config import Settings
        from agent33.evaluation.validation import validate_evaluation_config
        from agent33.llm.router import ModelRouter

        s = Settings(evaluation_judge_model="gpt-4o-mini")
        mock_provider = MagicMock()
        router = ModelRouter(providers={"openai": mock_provider})
        warnings = validate_evaluation_config(s, router)
        assert warnings == []

    def test_validate_warns_when_model_empty(self) -> None:
        """validate_evaluation_config warns when judge model is empty."""
        from agent33.config import Settings
        from agent33.evaluation.validation import validate_evaluation_config

        s = Settings(evaluation_judge_model="")
        warnings = validate_evaluation_config(s)
        assert len(warnings) == 1
        assert "empty" in warnings[0].lower()

    def test_validate_warns_when_model_not_routable(self) -> None:
        """validate_evaluation_config warns when model cannot be routed."""
        from agent33.config import Settings
        from agent33.evaluation.validation import validate_evaluation_config
        from agent33.llm.router import ModelRouter

        s = Settings(evaluation_judge_model="gpt-4o-mini")
        router = ModelRouter(providers={}, default_provider="none")
        warnings = validate_evaluation_config(s, router)
        assert len(warnings) == 1
        assert "no provider" in warnings[0].lower()

    def test_validate_without_router_only_checks_config(self) -> None:
        """validate_evaluation_config without router only checks if model is set."""
        from agent33.config import Settings
        from agent33.evaluation.validation import validate_evaluation_config

        s = Settings(evaluation_judge_model="some-model")
        warnings = validate_evaluation_config(s, model_router=None)
        assert warnings == []


# =========================================================================
# TestLLMEvaluatorRegistryWiring
# =========================================================================


class TestLLMEvaluatorRegistryWiring:
    """Tests that the LLM evaluator can be registered and retrieved correctly."""

    def test_llm_evaluator_coexists_with_rule_based(self) -> None:
        """LLM and rule-based evaluators can coexist in the same registry."""
        from agent33.evaluation.rule_based_evaluator import RuleBasedEvaluator

        registry = EvaluatorRegistry()
        rb = RuleBasedEvaluator()
        registry.register(rb)
        registry.set_default(rb.evaluator_id)

        router = _make_router()
        llm_ev = register_llm_evaluator(registry, router, "gpt-4o-mini")

        # Both are registered
        assert registry.get("rule_based_v1") is rb
        assert registry.get("llm_judge_v1") is llm_ev
        assert len(registry.list_ids()) == 2

        # Default is still rule-based
        default = registry.get_default()
        assert default is not None
        assert default.evaluator_id == "rule_based_v1"

    def test_llm_evaluator_can_become_default(self) -> None:
        """LLM evaluator can replace rule-based as the default."""
        from agent33.evaluation.rule_based_evaluator import RuleBasedEvaluator

        registry = EvaluatorRegistry()
        rb = RuleBasedEvaluator()
        registry.register(rb)
        registry.set_default(rb.evaluator_id)

        router = _make_router()
        register_llm_evaluator(registry, router, "gpt-4o")
        registry.set_default("llm_judge_v1")

        default = registry.get_default()
        assert default is not None
        assert default.evaluator_id == "llm_judge_v1"

    async def test_both_evaluators_produce_compatible_results(self) -> None:
        """Both evaluators produce EvaluationResult with compatible shapes."""
        from agent33.evaluation.rule_based_evaluator import RuleBasedEvaluator

        rb = RuleBasedEvaluator()
        router = _make_router(REALISTIC_PASS_RESPONSE)
        llm_ev = LLMEvaluator(model_router=router, model="m")

        inp = EvaluationInput(
            task_id="compat-1",
            prompt="What is 2+2?",
            actual_output="4",
            expected_output="4",
        )

        rb_result = await rb.evaluate(inp)
        llm_result = await llm_ev.evaluate(inp)

        # Both produce valid EvaluationResult with the same shape
        assert isinstance(rb_result, EvaluationResult)
        assert isinstance(llm_result, EvaluationResult)
        assert rb_result.task_id == llm_result.task_id == "compat-1"
        assert isinstance(rb_result.score, float)
        assert isinstance(llm_result.score, float)
        assert 0.0 <= rb_result.score <= 1.0
        assert 0.0 <= llm_result.score <= 1.0
        assert isinstance(rb_result.verdict, EvaluationVerdict)
        assert isinstance(llm_result.verdict, EvaluationVerdict)
        assert rb_result.evaluator_id == "rule_based_v1"
        assert llm_result.evaluator_id == "llm_judge_v1"


# =========================================================================
# TestRealisticEndToEndFlow
# =========================================================================


class TestRealisticEndToEndFlow:
    """End-to-end flow: config -> evaluator -> scores -> service -> gate."""

    async def test_end_to_end_passing_evaluation(self) -> None:
        """Complete end-to-end flow from LLM evaluation to gate pass."""
        # Step 1: Configure evaluator with realistic model
        responses = [
            {"verdict": "pass", "score": 0.92, "reason": "Correct implementation"},
            {"verdict": "pass", "score": 0.88, "reason": "Good coverage"},
            {"verdict": "pass", "score": 0.95, "reason": "Excellent quality"},
            {"verdict": "pass", "score": 0.85, "reason": "Acceptable with minor issues"},
            {"verdict": "fail", "score": 0.45, "reason": "Missing error handling"},
        ]
        router = _make_router_sequence(responses)
        ev = LLMEvaluator(model_router=router, model="gpt-4o-mini")

        # Step 2: Run evaluations
        inputs = [
            _make_input(task_id=f"e2e-{i}", prompt=f"Task {i}", actual=f"Output {i}")
            for i in range(5)
        ]
        eval_results = await ev.evaluate_batch(inputs)

        # Step 3: Convert to TaskRunResults
        task_results = []
        for er in eval_results:
            is_pass = er.verdict == EvaluationVerdict.PASS
            task_results.append(
                TaskRunResult(
                    item_id=er.task_id,
                    result=TaskResult.PASS if is_pass else TaskResult.FAIL,
                    checks_passed=1 if is_pass else 0,
                    checks_total=1,
                    duration_ms=100,
                )
            )

        # Step 4: Submit to EvaluationService
        service = EvaluationService()
        run = service.create_run(GateType.G_PR, commit_hash="e2e-test-hash")
        completed = service.submit_results(run.run_id, task_results)

        assert completed is not None
        assert completed.gate_report is not None
        # 4/5 = 80%, exactly at G-PR threshold
        assert completed.gate_report.overall == GateResult.PASS

        # Step 5: Verify metrics
        metric_map = {m.metric_id: m.value for m in completed.metrics}
        assert metric_map[MetricId.M_01] == pytest.approx(80.0)
        assert metric_map[MetricId.M_05] == pytest.approx(100.0)

    async def test_end_to_end_failing_evaluation(self) -> None:
        """Complete end-to-end flow where LLM failures cause gate failure."""
        # Too many fails for G-PR (needs >= 80%)
        responses = [
            {"verdict": "pass", "score": 0.90, "reason": "Good"},
            {"verdict": "fail", "score": 0.30, "reason": "Wrong"},
            {"verdict": "fail", "score": 0.20, "reason": "Incorrect"},
            {"verdict": "fail", "score": 0.15, "reason": "Missing"},
            {"verdict": "pass", "score": 0.85, "reason": "Ok"},
        ]
        router = _make_router_sequence(responses)
        ev = LLMEvaluator(model_router=router, model="gpt-4o-mini")

        inputs = [_make_input(task_id=f"e2e-fail-{i}") for i in range(5)]
        eval_results = await ev.evaluate_batch(inputs)

        task_results = []
        for er in eval_results:
            is_pass = er.verdict == EvaluationVerdict.PASS
            task_results.append(
                TaskRunResult(
                    item_id=er.task_id,
                    result=TaskResult.PASS if is_pass else TaskResult.FAIL,
                    checks_passed=1 if is_pass else 0,
                    checks_total=1,
                    duration_ms=100,
                )
            )

        service = EvaluationService()
        run = service.create_run(GateType.G_PR)
        completed = service.submit_results(run.run_id, task_results)

        assert completed is not None
        assert completed.gate_report is not None
        # 2/5 = 40%, well below G-PR 80% threshold
        assert completed.gate_report.overall == GateResult.FAIL

        metric_map = {m.metric_id: m.value for m in completed.metrics}
        assert metric_map[MetricId.M_01] == pytest.approx(40.0)

    async def test_end_to_end_with_mixed_errors_and_scores(self) -> None:
        """Pipeline handles a mix of LLM successes, failures, and errors."""
        call_count = 0

        async def _mixed_complete(messages: list, **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            if call_count == 2:
                # Simulate provider error on second call
                raise ConnectionError("Connection reset")
            if call_count == 4:
                # Simulate malformed response on fourth call
                resp.content = "NOT JSON"
                return resp
            # Normal responses for others
            resp.content = json.dumps({"verdict": "pass", "score": 0.90, "reason": "Good output"})
            return resp

        router = MagicMock()
        router.complete = AsyncMock(side_effect=_mixed_complete)
        ev = LLMEvaluator(model_router=router, model="m")

        inputs = [_make_input(task_id=f"mixed-{i}") for i in range(5)]
        eval_results = await ev.evaluate_batch(inputs)

        # Verify mixed results
        verdicts = [r.verdict for r in eval_results]
        assert EvaluationVerdict.PASS in verdicts
        assert EvaluationVerdict.ERROR in verdicts

        # Convert and check gate
        task_results = []
        for er in eval_results:
            is_pass = er.verdict == EvaluationVerdict.PASS
            task_results.append(
                TaskRunResult(
                    item_id=er.task_id,
                    result=TaskResult.PASS if is_pass else TaskResult.FAIL,
                    checks_passed=1 if is_pass else 0,
                    checks_total=1,
                    duration_ms=100,
                )
            )

        service = EvaluationService()
        run = service.create_run(GateType.G_PR)
        completed = service.submit_results(run.run_id, task_results)

        assert completed is not None
        assert completed.gate_report is not None
        # 3/5 = 60%, below G-PR 80% threshold
        assert completed.gate_report.overall == GateResult.FAIL


# =========================================================================
# Live provider tests (skipped in CI)
# =========================================================================


@pytest.mark.integration
class TestLLMEvaluatorLiveProvider:
    """Tests requiring actual LLM provider (skip in CI without credentials).

    These tests are gated behind the AGENT33_LLM_LIVE_TESTS=1 environment
    variable AND require valid provider credentials. They validate that the
    full pipeline works end-to-end with a real LLM.

    See also: test_llm_evaluator_live.py for more comprehensive live tests.
    """

    @pytest.fixture(autouse=True)
    def skip_without_provider(self) -> None:
        """Skip if no evaluation_judge_model or provider credentials available."""
        import os

        if os.environ.get("AGENT33_LLM_LIVE_TESTS") != "1":
            pytest.skip("Live LLM tests disabled (set AGENT33_LLM_LIVE_TESTS=1 to enable)")
        # Check for at least one provider credential
        has_openai = bool(os.environ.get("OPENAI_API_KEY"))
        has_judge = bool(os.environ.get("EVALUATION_JUDGE_MODEL"))
        if not has_openai and not has_judge:
            pytest.skip(
                "No LLM provider credentials available "
                "(set OPENAI_API_KEY or EVALUATION_JUDGE_MODEL)"
            )

    async def test_live_evaluation_end_to_end(self) -> None:
        """Full evaluation with real LLM provider, if available."""
        from agent33.config import Settings
        from agent33.llm.router import ModelRouter

        settings = Settings()
        model = settings.evaluation_judge_model or "gpt-4o-mini"
        router = ModelRouter()

        openai_key = settings.openai_api_key.get_secret_value()
        if openai_key:
            from agent33.llm.openai import OpenAIProvider

            provider = OpenAIProvider(
                api_key=openai_key,
                base_url=settings.openai_base_url or "https://api.openai.com/v1",
            )
            router.register("openai", provider)

        try:
            router.route(model)
        except ValueError:
            pytest.skip(f"No provider registered for model '{model}'")

        ev = LLMEvaluator(model_router=router, model=model)
        inp = EvaluationInput(
            task_id="live-integration-1",
            prompt="What is the capital of France?",
            actual_output="Paris",
            expected_output="Paris",
        )
        result = await ev.evaluate(inp)

        # Basic structural assertions
        assert result.task_id == "live-integration-1"
        assert isinstance(result.verdict, EvaluationVerdict)
        assert isinstance(result.score, float)
        assert 0.0 <= result.score <= 1.0
        assert isinstance(result.reason, str)
        assert result.evaluator_id == "llm_judge_v1"

        # For this trivially correct case, expect PASS
        assert result.verdict == EvaluationVerdict.PASS
        assert result.score >= 0.7
