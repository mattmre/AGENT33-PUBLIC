"""Extended offline tests for LLM evaluator.

These tests run without any live LLM provider. They cover:
- JSON parsing edge cases (markdown fences, missing fields, extra keys)
- Rubric-based evaluation flow end-to-end with mocked router
- Concurrent evaluation handling
- Score clamping boundary cases
- _parse_response internals
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent33.evaluation.evaluator_interface import (
    EvaluationInput,
    EvaluationVerdict,
)
from agent33.evaluation.llm_evaluator import LLMEvaluator

# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------


def _mock_router(
    response_text: str | None = None,
    response_json: dict | None = None,
    *,
    raise_exc: Exception | None = None,
) -> MagicMock:
    """Build a mock ModelRouter.

    Accepts either raw text or a dict (auto-serialized to JSON).
    """
    router = MagicMock()
    if raise_exc is not None:
        router.complete = AsyncMock(side_effect=raise_exc)
    else:
        if response_text is not None:
            payload = response_text
        else:
            payload = json.dumps(
                response_json or {"verdict": "pass", "score": 1.0, "reason": "ok"}
            )
        mock_resp = MagicMock()
        mock_resp.content = payload
        router.complete = AsyncMock(return_value=mock_resp)
    return router


def _mock_router_sequence(responses: list[str]) -> MagicMock:
    """Build a mock router that returns a sequence of raw text responses."""
    router = MagicMock()
    mock_resps = []
    for text in responses:
        resp = MagicMock()
        resp.content = text
        mock_resps.append(resp)
    router.complete = AsyncMock(side_effect=mock_resps)
    return router


def _make_input(
    *,
    task_id: str = "t1",
    prompt: str = "What is 2+2?",
    actual: str = "4",
    expected: str | None = "4",
) -> EvaluationInput:
    return EvaluationInput(
        task_id=task_id,
        prompt=prompt,
        actual_output=actual,
        expected_output=expected,
    )


# =========================================================================
# JSON parsing edge cases
# =========================================================================


class TestMarkdownFenceStripping:
    """The evaluator must strip markdown code fences that LLMs sometimes add."""

    async def test_json_fence_stripped(self) -> None:
        """```json ... ``` wrapper is stripped and parsed."""
        raw = '```json\n{"verdict": "pass", "score": 0.9, "reason": "good"}\n```'
        router = _mock_router(response_text=raw)
        ev = LLMEvaluator(model_router=router, model="m")
        result = await ev.evaluate(_make_input())
        assert result.verdict == EvaluationVerdict.PASS
        assert result.score == pytest.approx(0.9)
        assert result.reason == "good"

    async def test_bare_fence_stripped(self) -> None:
        """``` ... ``` wrapper (no language tag) is stripped and parsed."""
        raw = '```\n{"verdict": "fail", "score": 0.1, "reason": "wrong"}\n```'
        router = _mock_router(response_text=raw)
        ev = LLMEvaluator(model_router=router, model="m")
        result = await ev.evaluate(_make_input())
        assert result.verdict == EvaluationVerdict.FAIL
        assert result.score == pytest.approx(0.1)

    async def test_fence_with_trailing_whitespace(self) -> None:
        """Trailing whitespace around fenced JSON is tolerated."""
        raw = '```json\n  {"verdict": "pass", "score": 1.0, "reason": "exact"}  \n```'
        router = _mock_router(response_text=raw)
        ev = LLMEvaluator(model_router=router, model="m")
        result = await ev.evaluate(_make_input())
        assert result.verdict == EvaluationVerdict.PASS

    async def test_fence_multiline_json(self) -> None:
        """Multi-line JSON inside fences is handled."""
        raw = (
            "```json\n"
            "{\n"
            '  "verdict": "pass",\n'
            '  "score": 0.85,\n'
            '  "reason": "mostly correct"\n'
            "}\n"
            "```"
        )
        router = _mock_router(response_text=raw)
        ev = LLMEvaluator(model_router=router, model="m")
        result = await ev.evaluate(_make_input())
        assert result.verdict == EvaluationVerdict.PASS
        assert result.score == pytest.approx(0.85)
        assert result.reason == "mostly correct"


class TestJsonParsingEdgeCases:
    """Various malformed or edge-case JSON responses."""

    async def test_extra_keys_ignored(self) -> None:
        """Extra keys in the JSON response are silently ignored."""
        raw = json.dumps(
            {
                "verdict": "pass",
                "score": 0.95,
                "reason": "good",
                "confidence": 0.99,
                "model_notes": "extra data",
            }
        )
        router = _mock_router(response_text=raw)
        ev = LLMEvaluator(model_router=router, model="m")
        result = await ev.evaluate(_make_input())
        assert result.verdict == EvaluationVerdict.PASS
        assert result.score == pytest.approx(0.95)

    async def test_nested_objects_in_reason(self) -> None:
        """A reason containing nested JSON-like text is preserved as string."""
        raw = json.dumps(
            {
                "verdict": "pass",
                "score": 0.8,
                "reason": 'Input matched pattern {"key": "value"}',
            }
        )
        router = _mock_router(response_text=raw)
        ev = LLMEvaluator(model_router=router, model="m")
        result = await ev.evaluate(_make_input())
        assert result.verdict == EvaluationVerdict.PASS
        assert '{"key": "value"}' in result.reason

    async def test_unicode_in_reason(self) -> None:
        """Unicode characters in the reason field are preserved."""
        raw = json.dumps(
            {
                "verdict": "pass",
                "score": 0.9,
                "reason": "Correct answer provided",
            }
        )
        router = _mock_router(response_text=raw)
        ev = LLMEvaluator(model_router=router, model="m")
        result = await ev.evaluate(_make_input())
        assert result.reason == "Correct answer provided"

    async def test_completely_empty_response(self) -> None:
        """Empty string response is a parse error."""
        router = _mock_router(response_text="")
        ev = LLMEvaluator(model_router=router, model="m")
        result = await ev.evaluate(_make_input())
        assert result.verdict == EvaluationVerdict.ERROR
        assert "parse" in result.reason.lower() or "json" in result.reason.lower()

    async def test_whitespace_only_response(self) -> None:
        """Whitespace-only response is a parse error."""
        router = _mock_router(response_text="   \n\t  ")
        ev = LLMEvaluator(model_router=router, model="m")
        result = await ev.evaluate(_make_input())
        assert result.verdict == EvaluationVerdict.ERROR

    async def test_html_response_is_error(self) -> None:
        """HTML response (common in proxy errors) is a parse error."""
        router = _mock_router(response_text="<html><body>502 Bad Gateway</body></html>")
        ev = LLMEvaluator(model_router=router, model="m")
        result = await ev.evaluate(_make_input())
        assert result.verdict == EvaluationVerdict.ERROR

    async def test_json_array_response_returns_error(self) -> None:
        """A JSON array (instead of object) is gracefully handled as ERROR.

        json.loads succeeds on an array, but list has no .get() method.
        The type guard catches this and returns an ERROR result with
        a descriptive reason instead of raising AttributeError.
        """
        router = _mock_router(response_text='[{"verdict": "pass"}]')
        ev = LLMEvaluator(model_router=router, model="m")
        result = await ev.evaluate(_make_input())
        assert result.verdict == EvaluationVerdict.ERROR
        assert result.score == 0.0
        assert "list" in result.reason.lower()
        assert "JSON object" in result.reason
        assert result.evaluator_id == "llm_judge_v1"
        assert result.task_id == "t1"

    async def test_numeric_verdict_treated_as_unknown(self) -> None:
        """Numeric verdict value is stringified and rejected as unknown."""
        raw = json.dumps({"verdict": 1, "score": 0.8, "reason": "ok"})
        router = _mock_router(response_text=raw)
        ev = LLMEvaluator(model_router=router, model="m")
        result = await ev.evaluate(_make_input())
        assert result.verdict == EvaluationVerdict.ERROR
        assert "1" in result.reason

    async def test_null_verdict_treated_as_unknown(self) -> None:
        """null verdict is stringified to 'None' which is not a valid verdict."""
        raw = json.dumps({"verdict": None, "score": 0.5, "reason": "n/a"})
        router = _mock_router(response_text=raw)
        ev = LLMEvaluator(model_router=router, model="m")
        result = await ev.evaluate(_make_input())
        assert result.verdict == EvaluationVerdict.ERROR

    async def test_boolean_score_coerced_to_float(self) -> None:
        """Boolean score (True=1.0, False=0.0) is coerced via float()."""
        raw = json.dumps({"verdict": "pass", "score": True, "reason": "ok"})
        router = _mock_router(response_text=raw)
        ev = LLMEvaluator(model_router=router, model="m")
        result = await ev.evaluate(_make_input())
        assert result.verdict == EvaluationVerdict.PASS
        assert result.score == pytest.approx(1.0)

    async def test_string_score_that_is_parseable(self) -> None:
        """String score like "0.75" is coerced via float()."""
        raw = json.dumps({"verdict": "pass", "score": "0.75", "reason": "ok"})
        router = _mock_router(response_text=raw)
        ev = LLMEvaluator(model_router=router, model="m")
        result = await ev.evaluate(_make_input())
        assert result.verdict == EvaluationVerdict.PASS
        assert result.score == pytest.approx(0.75)

    async def test_string_score_unparseable_is_error(self) -> None:
        """Non-numeric string score causes a ValueError in float() -> ERROR."""
        raw = json.dumps({"verdict": "pass", "score": "high", "reason": "ok"})
        router = _mock_router(response_text=raw)
        ev = LLMEvaluator(model_router=router, model="m")
        result = await ev.evaluate(_make_input())
        assert result.verdict == EvaluationVerdict.ERROR


# =========================================================================
# _parse_response direct testing
# =========================================================================


class TestParseResponseDirect:
    """Test the _parse_response helper directly for finer-grained coverage."""

    def _evaluator(self) -> LLMEvaluator:
        return LLMEvaluator(model_router=MagicMock(), model="m")

    def test_valid_pass(self) -> None:
        ev = self._evaluator()
        raw = json.dumps({"verdict": "pass", "score": 0.9, "reason": "correct"})
        result = ev._parse_response("t1", raw)
        assert result.verdict == EvaluationVerdict.PASS
        assert result.score == pytest.approx(0.9)
        assert result.reason == "correct"

    def test_valid_fail(self) -> None:
        ev = self._evaluator()
        raw = json.dumps({"verdict": "fail", "score": 0.2, "reason": "wrong"})
        result = ev._parse_response("t2", raw)
        assert result.verdict == EvaluationVerdict.FAIL
        assert result.score == pytest.approx(0.2)

    def test_valid_skip(self) -> None:
        ev = self._evaluator()
        raw = json.dumps({"verdict": "skip", "score": 0.5, "reason": "uncertain"})
        result = ev._parse_response("t3", raw)
        assert result.verdict == EvaluationVerdict.SKIP

    def test_unknown_verdict_returns_error(self) -> None:
        ev = self._evaluator()
        raw = json.dumps({"verdict": "maybe", "score": 0.5, "reason": "unsure"})
        result = ev._parse_response("t4", raw)
        assert result.verdict == EvaluationVerdict.ERROR
        assert "maybe" in result.reason

    def test_invalid_json_returns_error(self) -> None:
        ev = self._evaluator()
        result = ev._parse_response("t5", "not json")
        assert result.verdict == EvaluationVerdict.ERROR
        assert result.score == 0.0

    def test_score_clamped_high(self) -> None:
        ev = self._evaluator()
        raw = json.dumps({"verdict": "pass", "score": 999.0, "reason": "over"})
        result = ev._parse_response("t6", raw)
        assert result.score == 1.0

    def test_score_clamped_low(self) -> None:
        ev = self._evaluator()
        raw = json.dumps({"verdict": "fail", "score": -999.0, "reason": "under"})
        result = ev._parse_response("t7", raw)
        assert result.score == 0.0

    def test_case_insensitive_verdict(self) -> None:
        """The evaluator lowercases the verdict before matching."""
        ev = self._evaluator()
        raw = json.dumps({"verdict": "PASS", "score": 1.0, "reason": "ok"})
        result = ev._parse_response("t8", raw)
        assert result.verdict == EvaluationVerdict.PASS

    def test_verdict_with_whitespace(self) -> None:
        """Whitespace-padded verdict string is not automatically trimmed by
        the current implementation -- str() preserves it, and StrEnum won't
        match ' pass '. This should be ERROR."""
        ev = self._evaluator()
        raw = json.dumps({"verdict": " pass ", "score": 1.0, "reason": "ok"})
        result = ev._parse_response("t9", raw)
        # " pass " lowered is " pass " which is not a valid verdict enum value
        assert result.verdict == EvaluationVerdict.ERROR

    def test_fence_strip_preserves_interior(self) -> None:
        """_parse_response receives already-stripped text from evaluate(),
        but we test the stripping path explicitly."""
        ev = self._evaluator()
        raw = '```json\n{"verdict": "pass", "score": 1.0, "reason": "fenced"}\n```'
        result = ev._parse_response("t10", raw)
        assert result.verdict == EvaluationVerdict.PASS
        assert result.reason == "fenced"

    def test_task_id_propagation(self) -> None:
        """The task_id is always propagated from the call site."""
        ev = self._evaluator()
        raw = json.dumps({"verdict": "pass", "score": 0.8, "reason": "ok"})
        result = ev._parse_response("custom-id-42", raw)
        assert result.task_id == "custom-id-42"

    def test_evaluator_id_set(self) -> None:
        """The evaluator_id is always set to the evaluator's id."""
        ev = self._evaluator()
        raw = json.dumps({"verdict": "pass", "score": 0.8, "reason": "ok"})
        result = ev._parse_response("t11", raw)
        assert result.evaluator_id == "llm_judge_v1"


# =========================================================================
# Rubric-based evaluation flow (end-to-end with mock)
# =========================================================================


class TestRubricEvaluationFlow:
    """Simulates a full evaluation flow with rubric-style prompts."""

    async def test_code_correctness_rubric(self) -> None:
        """Evaluate code correctness: correct implementation passes."""
        router = _mock_router(
            response_json={"verdict": "pass", "score": 0.95, "reason": "Implementation correct"}
        )
        ev = LLMEvaluator(model_router=router, model="gpt-4o-mini")
        inp = EvaluationInput(
            task_id="code-correct-1",
            prompt="Implement a function that returns the sum of two numbers",
            actual_output="def add(a, b): return a + b",
            expected_output="A function that takes two args and returns their sum",
        )
        result = await ev.evaluate(inp)
        assert result.verdict == EvaluationVerdict.PASS
        assert result.score >= 0.9

        # Verify the router was called with the correct structure
        router.complete.assert_called_once()
        messages = router.complete.call_args[0][0]
        assert len(messages) == 2
        assert "evaluation judge" in messages[0].content.lower()
        assert "code-correct-1" in messages[1].content
        assert "def add(a, b)" in messages[1].content

    async def test_code_correctness_rubric_fail(self) -> None:
        """Evaluate code correctness: wrong implementation fails."""
        router = _mock_router(
            response_json={
                "verdict": "fail",
                "score": 0.1,
                "reason": "Returns multiplication instead of sum",
            }
        )
        ev = LLMEvaluator(model_router=router, model="gpt-4o-mini")
        inp = EvaluationInput(
            task_id="code-wrong-1",
            prompt="Implement a function that returns the sum of two numbers",
            actual_output="def add(a, b): return a * b",
            expected_output="A function that takes two args and returns their sum",
        )
        result = await ev.evaluate(inp)
        assert result.verdict == EvaluationVerdict.FAIL
        assert result.score < 0.7
        assert "multiplication" in result.reason.lower()

    async def test_multi_criterion_evaluation(self) -> None:
        """Multi-criterion: LLM considers multiple factors in its judgment."""
        router = _mock_router(
            response_json={
                "verdict": "pass",
                "score": 0.75,
                "reason": "Functionally correct but poor naming and no docstring",
            }
        )
        ev = LLMEvaluator(model_router=router, model="judge")
        inp = EvaluationInput(
            task_id="multi-criterion-1",
            prompt="Write a well-documented Python function to reverse a string",
            actual_output="def f(s): return s[::-1]",
            expected_output="A documented function that reverses a string",
        )
        result = await ev.evaluate(inp)
        assert result.verdict == EvaluationVerdict.PASS
        assert result.score == pytest.approx(0.75)
        assert "naming" in result.reason.lower() or "docstring" in result.reason.lower()

    async def test_evaluation_with_metadata_in_input(self) -> None:
        """Metadata in EvaluationInput is carried through (not sent to LLM)."""
        router = _mock_router(response_json={"verdict": "pass", "score": 0.9, "reason": "Good"})
        ev = LLMEvaluator(model_router=router, model="m")
        inp = EvaluationInput(
            task_id="meta-1",
            prompt="Explain X",
            actual_output="X is ...",
            expected_output="X is a thing",
            metadata={"category": "explanation", "difficulty": "easy"},
        )
        result = await ev.evaluate(inp)
        assert result.verdict == EvaluationVerdict.PASS
        # Metadata from input is not in the result metadata by default,
        # but the result should still be correctly formed
        assert result.task_id == "meta-1"


# =========================================================================
# Concurrent evaluation
# =========================================================================


class TestConcurrentEvaluations:
    """Test concurrent evaluation handling via evaluate_batch and parallel calls."""

    async def test_batch_concurrent_execution(self) -> None:
        """evaluate_batch runs evaluations concurrently via asyncio.gather."""
        call_count = 0
        call_order: list[str] = []

        async def _delayed_complete(messages, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal call_count
            call_count += 1
            task_content = messages[1].content
            # Extract task ID from the message content
            for line in task_content.splitlines():
                if line.startswith("Task ID:"):
                    tid = line.split(":", 1)[1].strip()
                    call_order.append(tid)
                    break
            # Small delay to allow interleaving
            await asyncio.sleep(0.01)
            resp = MagicMock()
            resp.content = json.dumps({"verdict": "pass", "score": 0.8, "reason": "ok"})
            return resp

        router = MagicMock()
        router.complete = AsyncMock(side_effect=_delayed_complete)

        ev = LLMEvaluator(model_router=router, model="m")
        inputs = [_make_input(task_id=f"conc-{i}") for i in range(5)]
        results = await ev.evaluate_batch(inputs)

        assert len(results) == 5
        assert call_count == 5
        # All task IDs should be present (order may vary due to concurrency)
        result_ids = {r.task_id for r in results}
        assert result_ids == {f"conc-{i}" for i in range(5)}

    async def test_batch_partial_failure(self) -> None:
        """When one evaluation fails, others still succeed."""
        responses = [
            json.dumps({"verdict": "pass", "score": 1.0, "reason": "ok"}),
            "INVALID JSON",
            json.dumps({"verdict": "fail", "score": 0.3, "reason": "wrong"}),
        ]
        router = _mock_router_sequence(responses)
        ev = LLMEvaluator(model_router=router, model="m")

        inputs = [_make_input(task_id=f"partial-{i}") for i in range(3)]
        results = await ev.evaluate_batch(inputs)

        assert len(results) == 3
        assert results[0].verdict == EvaluationVerdict.PASS
        assert results[1].verdict == EvaluationVerdict.ERROR  # parse error
        assert results[2].verdict == EvaluationVerdict.FAIL

    async def test_batch_all_skip(self) -> None:
        """Batch where all inputs have no expected output -- all skip, no LLM calls."""
        router = _mock_router()
        ev = LLMEvaluator(model_router=router, model="m")
        inputs = [_make_input(task_id=f"skip-{i}", expected=None) for i in range(4)]
        results = await ev.evaluate_batch(inputs)

        assert len(results) == 4
        assert all(r.verdict == EvaluationVerdict.SKIP for r in results)
        router.complete.assert_not_called()

    async def test_batch_with_provider_exception_on_one(self) -> None:
        """One provider exception does not crash the entire batch."""
        call_idx = 0

        async def _flaky_complete(messages, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal call_idx
            call_idx += 1
            if call_idx == 2:
                raise ConnectionError("Provider timeout")
            resp = MagicMock()
            resp.content = json.dumps({"verdict": "pass", "score": 0.9, "reason": "ok"})
            return resp

        router = MagicMock()
        router.complete = AsyncMock(side_effect=_flaky_complete)

        ev = LLMEvaluator(model_router=router, model="m")
        inputs = [_make_input(task_id=f"flaky-{i}") for i in range(3)]
        results = await ev.evaluate_batch(inputs)

        assert len(results) == 3
        # Exactly one should be ERROR due to the connection error
        error_results = [r for r in results if r.verdict == EvaluationVerdict.ERROR]
        pass_results = [r for r in results if r.verdict == EvaluationVerdict.PASS]
        assert len(error_results) == 1
        assert len(pass_results) == 2
        assert "Provider timeout" in error_results[0].reason

    async def test_parallel_independent_evaluations(self) -> None:
        """Two independent evaluate() calls on the same evaluator run fine."""
        router = _mock_router(response_json={"verdict": "pass", "score": 0.85, "reason": "ok"})
        ev = LLMEvaluator(model_router=router, model="m")

        result_a, result_b = await asyncio.gather(
            ev.evaluate(_make_input(task_id="parallel-a")),
            ev.evaluate(_make_input(task_id="parallel-b")),
        )
        assert result_a.task_id == "parallel-a"
        assert result_b.task_id == "parallel-b"
        assert result_a.verdict == EvaluationVerdict.PASS
        assert result_b.verdict == EvaluationVerdict.PASS


# =========================================================================
# Score boundary and clamping
# =========================================================================


class TestScoreBoundaries:
    """Comprehensive score clamping and boundary tests."""

    @pytest.mark.parametrize(
        ("raw_score", "expected_clamped"),
        [
            (0.0, 0.0),
            (0.5, 0.5),
            (1.0, 1.0),
            (-0.001, 0.0),
            (1.001, 1.0),
            (-100.0, 0.0),
            (100.0, 1.0),
        ],
    )
    async def test_score_clamping(self, raw_score: float, expected_clamped: float) -> None:
        router = _mock_router(
            response_json={"verdict": "pass", "score": raw_score, "reason": "test"}
        )
        ev = LLMEvaluator(model_router=router, model="m")
        result = await ev.evaluate(_make_input())
        assert result.score == pytest.approx(expected_clamped)


# =========================================================================
# Provider error handling
# =========================================================================


class TestProviderErrorHandling:
    """Various provider error scenarios."""

    async def test_timeout_error(self) -> None:
        router = _mock_router(raise_exc=TimeoutError("Request timed out"))
        ev = LLMEvaluator(model_router=router, model="m")
        result = await ev.evaluate(_make_input())
        assert result.verdict == EvaluationVerdict.ERROR
        assert "timed out" in result.reason.lower()

    async def test_connection_error(self) -> None:
        router = _mock_router(raise_exc=ConnectionError("Connection refused"))
        ev = LLMEvaluator(model_router=router, model="m")
        result = await ev.evaluate(_make_input())
        assert result.verdict == EvaluationVerdict.ERROR
        assert "connection" in result.reason.lower()

    async def test_value_error_from_provider(self) -> None:
        router = _mock_router(raise_exc=ValueError("Invalid model"))
        ev = LLMEvaluator(model_router=router, model="m")
        result = await ev.evaluate(_make_input())
        assert result.verdict == EvaluationVerdict.ERROR
        assert "Invalid model" in result.reason

    async def test_generic_exception_caught(self) -> None:
        router = _mock_router(raise_exc=RuntimeError("Unexpected error"))
        ev = LLMEvaluator(model_router=router, model="m")
        result = await ev.evaluate(_make_input())
        assert result.verdict == EvaluationVerdict.ERROR
        assert "Unexpected error" in result.reason

    async def test_error_result_has_zero_score(self) -> None:
        router = _mock_router(raise_exc=RuntimeError("boom"))
        ev = LLMEvaluator(model_router=router, model="m")
        result = await ev.evaluate(_make_input())
        assert result.score == 0.0

    async def test_error_result_has_correct_evaluator_id(self) -> None:
        router = _mock_router(raise_exc=RuntimeError("boom"))
        ev = LLMEvaluator(model_router=router, model="m")
        result = await ev.evaluate(_make_input())
        assert result.evaluator_id == "llm_judge_v1"

    async def test_error_result_has_correct_task_id(self) -> None:
        router = _mock_router(raise_exc=RuntimeError("boom"))
        ev = LLMEvaluator(model_router=router, model="m")
        result = await ev.evaluate(_make_input(task_id="err-task-77"))
        assert result.task_id == "err-task-77"


# =========================================================================
# Evaluator registry integration
# =========================================================================


class TestEvaluatorRegistryIntegration:
    """Test LLMEvaluator interaction with the EvaluatorRegistry."""

    def test_register_and_lookup(self) -> None:
        from agent33.evaluation.evaluator_registry import EvaluatorRegistry

        router = _mock_router()
        registry = EvaluatorRegistry()
        ev = LLMEvaluator(model_router=router, model="judge")
        registry.register(ev)
        assert registry.get("llm_judge_v1") is ev

    def test_register_overwrites_existing(self) -> None:
        from agent33.evaluation.evaluator_registry import EvaluatorRegistry

        router1 = _mock_router()
        router2 = _mock_router()
        registry = EvaluatorRegistry()
        ev1 = LLMEvaluator(model_router=router1, model="model-a")
        ev2 = LLMEvaluator(model_router=router2, model="model-b")
        registry.register(ev1)
        registry.register(ev2)
        # Both have same evaluator_id, so ev2 overwrites ev1
        assert registry.get("llm_judge_v1") is ev2

    def test_set_as_default(self) -> None:
        from agent33.evaluation.evaluator_registry import EvaluatorRegistry

        router = _mock_router()
        registry = EvaluatorRegistry()
        ev = LLMEvaluator(model_router=router, model="m")
        registry.register(ev)
        registry.set_default("llm_judge_v1")
        assert registry.get_default() is ev

    def test_list_ids_includes_llm_evaluator(self) -> None:
        from agent33.evaluation.evaluator_registry import EvaluatorRegistry

        router = _mock_router()
        registry = EvaluatorRegistry()
        ev = LLMEvaluator(model_router=router, model="m")
        registry.register(ev)
        assert "llm_judge_v1" in registry.list_ids()


# =========================================================================
# Construction validation
# =========================================================================


class TestConstructionValidation:
    """Validates constructor edge cases."""

    def test_empty_model_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            LLMEvaluator(model_router=MagicMock(), model="")

    def test_whitespace_model_accepted(self) -> None:
        """A model name that is just whitespace is technically non-empty."""
        ev = LLMEvaluator(model_router=MagicMock(), model="  ")
        assert ev._model == "  "

    def test_evaluator_id_is_stable(self) -> None:
        ev = LLMEvaluator(model_router=MagicMock(), model="any-model")
        assert ev.evaluator_id == "llm_judge_v1"

    def test_satisfies_evaluator_protocol(self) -> None:
        from agent33.evaluation.evaluator_interface import Evaluator

        ev = LLMEvaluator(model_router=MagicMock(), model="m")
        assert isinstance(ev, Evaluator)
