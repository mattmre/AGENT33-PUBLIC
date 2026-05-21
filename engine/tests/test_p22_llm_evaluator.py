"""Tests for P2.2 LLM-backed evaluator."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent33.evaluation.evaluator_interface import (
    EvaluationInput,
    EvaluationVerdict,
)
from agent33.evaluation.evaluator_registry import (
    EvaluatorRegistry,
    register_llm_evaluator,
)
from agent33.evaluation.llm_evaluator import LLMEvaluator

# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------


def _make_router(
    response_json: dict | None = None,
    *,
    raise_exc: Exception | None = None,
) -> MagicMock:
    """Return a mock ModelRouter whose complete() returns the given JSON."""
    router = MagicMock()
    if raise_exc is not None:
        router.complete = AsyncMock(side_effect=raise_exc)
    else:
        payload = json.dumps(response_json or {"verdict": "pass", "score": 1.0, "reason": "ok"})
        mock_response = MagicMock()
        mock_response.content = payload
        router.complete = AsyncMock(return_value=mock_response)
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


# -------------------------------------------------------------------------
# Construction
# -------------------------------------------------------------------------


def test_evaluator_id() -> None:
    router = _make_router()
    ev = LLMEvaluator(model_router=router, model="test-model")
    assert ev.evaluator_id == "llm_judge_v1"


def test_empty_model_raises() -> None:
    router = _make_router()
    with pytest.raises(ValueError, match="non-empty"):
        LLMEvaluator(model_router=router, model="")


def test_satisfies_evaluator_protocol() -> None:
    from agent33.evaluation.evaluator_interface import Evaluator

    router = _make_router()
    ev = LLMEvaluator(model_router=router, model="m")
    assert isinstance(ev, Evaluator)


# -------------------------------------------------------------------------
# evaluate() --- SKIP when no expected output
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_skip_no_expected_output() -> None:
    router = _make_router()
    ev = LLMEvaluator(model_router=router, model="m")
    result = await ev.evaluate(_make_input(expected=None))
    assert result.verdict == EvaluationVerdict.SKIP
    assert result.score == 0.5
    assert result.task_id == "t1"
    router.complete.assert_not_called()


@pytest.mark.asyncio
async def test_evaluate_skip_does_not_call_llm() -> None:
    router = _make_router()
    ev = LLMEvaluator(model_router=router, model="m")
    await ev.evaluate(_make_input(expected=None))
    router.complete.assert_not_called()


# -------------------------------------------------------------------------
# evaluate() --- PASS
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_pass_verdict() -> None:
    router = _make_router({"verdict": "pass", "score": 1.0, "reason": "correct"})
    ev = LLMEvaluator(model_router=router, model="judge-model")
    result = await ev.evaluate(_make_input())
    assert result.verdict == EvaluationVerdict.PASS
    assert result.score == 1.0
    assert result.reason == "correct"
    assert result.evaluator_id == "llm_judge_v1"


@pytest.mark.asyncio
async def test_evaluate_pass_calls_router_with_zero_temperature() -> None:
    router = _make_router({"verdict": "pass", "score": 0.9, "reason": "ok"})
    ev = LLMEvaluator(model_router=router, model="judge-model")
    await ev.evaluate(_make_input())
    router.complete.assert_called_once()
    _, kwargs = router.complete.call_args
    assert kwargs["temperature"] == 0.0
    assert kwargs["model"] == "judge-model"


# -------------------------------------------------------------------------
# evaluate() --- FAIL
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_fail_verdict() -> None:
    router = _make_router({"verdict": "fail", "score": 0.0, "reason": "wrong"})
    ev = LLMEvaluator(model_router=router, model="m")
    result = await ev.evaluate(_make_input(actual="wrong", expected="4"))
    assert result.verdict == EvaluationVerdict.FAIL
    assert result.score == 0.0


@pytest.mark.asyncio
async def test_evaluate_fail_partial_score() -> None:
    router = _make_router({"verdict": "fail", "score": 0.4, "reason": "partial"})
    ev = LLMEvaluator(model_router=router, model="m")
    result = await ev.evaluate(_make_input())
    assert result.score == pytest.approx(0.4)


# -------------------------------------------------------------------------
# evaluate() --- ERROR paths
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_error_on_invalid_json() -> None:
    router = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "not json at all"
    router.complete = AsyncMock(return_value=mock_response)
    ev = LLMEvaluator(model_router=router, model="m")
    result = await ev.evaluate(_make_input())
    assert result.verdict == EvaluationVerdict.ERROR
    assert result.score == 0.0
    assert "parse" in result.reason.lower() or "json" in result.reason.lower()


@pytest.mark.asyncio
async def test_evaluate_error_on_provider_exception() -> None:
    router = _make_router(raise_exc=RuntimeError("provider down"))
    ev = LLMEvaluator(model_router=router, model="m")
    result = await ev.evaluate(_make_input())
    assert result.verdict == EvaluationVerdict.ERROR
    assert "provider down" in result.reason


@pytest.mark.asyncio
async def test_evaluate_error_on_unknown_verdict_string() -> None:
    router = _make_router({"verdict": "maybe", "score": 0.5, "reason": "unsure"})
    ev = LLMEvaluator(model_router=router, model="m")
    result = await ev.evaluate(_make_input())
    assert result.verdict == EvaluationVerdict.ERROR
    assert "maybe" in result.reason


# -------------------------------------------------------------------------
# evaluate() --- score clamping
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_score_clamped_above_one() -> None:
    router = _make_router({"verdict": "pass", "score": 1.5, "reason": "over"})
    ev = LLMEvaluator(model_router=router, model="m")
    result = await ev.evaluate(_make_input())
    assert result.score <= 1.0


@pytest.mark.asyncio
async def test_evaluate_score_clamped_below_zero() -> None:
    router = _make_router({"verdict": "fail", "score": -0.5, "reason": "under"})
    ev = LLMEvaluator(model_router=router, model="m")
    result = await ev.evaluate(_make_input())
    assert result.score >= 0.0


# -------------------------------------------------------------------------
# evaluate() --- task_id propagation
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_task_id_propagated() -> None:
    router = _make_router({"verdict": "pass", "score": 1.0, "reason": "ok"})
    ev = LLMEvaluator(model_router=router, model="m")
    result = await ev.evaluate(_make_input(task_id="custom-task-99"))
    assert result.task_id == "custom-task-99"


# -------------------------------------------------------------------------
# evaluate() --- prompt content verification
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_sends_system_and_user_messages() -> None:
    router = _make_router({"verdict": "pass", "score": 0.8, "reason": "good"})
    ev = LLMEvaluator(model_router=router, model="m")
    inp = _make_input(task_id="t42", prompt="Explain X", actual="answer", expected="ref")
    await ev.evaluate(inp)
    router.complete.assert_called_once()
    messages = router.complete.call_args[0][0]
    assert len(messages) == 2
    assert messages[0].role == "system"
    assert messages[1].role == "user"
    assert "t42" in messages[1].content
    assert "Explain X" in messages[1].content
    assert "answer" in messages[1].content
    assert "ref" in messages[1].content


@pytest.mark.asyncio
async def test_evaluate_passes_max_tokens_256() -> None:
    router = _make_router({"verdict": "pass", "score": 1.0, "reason": "ok"})
    ev = LLMEvaluator(model_router=router, model="m")
    await ev.evaluate(_make_input())
    _, kwargs = router.complete.call_args
    assert kwargs["max_tokens"] == 256


# -------------------------------------------------------------------------
# evaluate() --- edge: empty reason and zero score in valid JSON
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_empty_reason_preserved() -> None:
    router = _make_router({"verdict": "pass", "score": 0.9, "reason": ""})
    ev = LLMEvaluator(model_router=router, model="m")
    result = await ev.evaluate(_make_input())
    assert result.reason == ""
    assert result.verdict == EvaluationVerdict.PASS


@pytest.mark.asyncio
async def test_evaluate_zero_score_with_pass_verdict() -> None:
    router = _make_router({"verdict": "pass", "score": 0.0, "reason": "odd"})
    ev = LLMEvaluator(model_router=router, model="m")
    result = await ev.evaluate(_make_input())
    assert result.verdict == EvaluationVerdict.PASS
    assert result.score == 0.0


# -------------------------------------------------------------------------
# evaluate() --- edge: LLM returns JSON with missing keys
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_missing_verdict_key_returns_error() -> None:
    router = _make_router({"score": 0.8, "reason": "no verdict"})
    ev = LLMEvaluator(model_router=router, model="m")
    result = await ev.evaluate(_make_input())
    # Missing "verdict" defaults to "" which is not a valid EvaluationVerdict
    assert result.verdict == EvaluationVerdict.ERROR


@pytest.mark.asyncio
async def test_evaluate_missing_score_key_defaults_to_zero() -> None:
    router = _make_router({"verdict": "pass", "reason": "no score"})
    ev = LLMEvaluator(model_router=router, model="m")
    result = await ev.evaluate(_make_input())
    assert result.score == 0.0
    assert result.verdict == EvaluationVerdict.PASS


# -------------------------------------------------------------------------
# evaluate() --- skip verdict from LLM
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_skip_verdict_from_llm() -> None:
    router = _make_router({"verdict": "skip", "score": 0.5, "reason": "uncertain"})
    ev = LLMEvaluator(model_router=router, model="m")
    result = await ev.evaluate(_make_input())
    assert result.verdict == EvaluationVerdict.SKIP
    assert result.score == 0.5


# -------------------------------------------------------------------------
# evaluate_batch()
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_batch_returns_same_order() -> None:
    def _resp(d: dict) -> MagicMock:
        r = MagicMock()
        r.content = json.dumps(d)
        return r

    router = MagicMock()
    router.complete = AsyncMock(
        side_effect=[
            _resp({"verdict": "pass", "score": 1.0, "reason": "a"}),
            _resp({"verdict": "fail", "score": 0.0, "reason": "b"}),
            _resp({"verdict": "pass", "score": 0.8, "reason": "c"}),
        ]
    )

    ev = LLMEvaluator(model_router=router, model="m")
    inputs = [
        _make_input(task_id="t1"),
        _make_input(task_id="t2"),
        _make_input(task_id="t3"),
    ]
    results = await ev.evaluate_batch(inputs)
    assert len(results) == 3
    assert results[0].task_id == "t1"
    assert results[1].task_id == "t2"
    assert results[2].task_id == "t3"
    assert results[0].verdict == EvaluationVerdict.PASS
    assert results[1].verdict == EvaluationVerdict.FAIL


@pytest.mark.asyncio
async def test_evaluate_batch_empty_list() -> None:
    router = _make_router()
    ev = LLMEvaluator(model_router=router, model="m")
    results = await ev.evaluate_batch([])
    assert results == []
    router.complete.assert_not_called()


@pytest.mark.asyncio
async def test_evaluate_batch_mixed_with_skip() -> None:
    """Batch with some inputs having no expected output should skip those."""
    router = _make_router({"verdict": "pass", "score": 0.9, "reason": "good"})
    ev = LLMEvaluator(model_router=router, model="m")
    inputs = [
        _make_input(task_id="t1", expected="ref"),
        _make_input(task_id="t2", expected=None),
    ]
    results = await ev.evaluate_batch(inputs)
    assert len(results) == 2
    assert results[0].verdict == EvaluationVerdict.PASS
    assert results[1].verdict == EvaluationVerdict.SKIP
    # Only one LLM call should have been made (the None-expected skips)
    router.complete.assert_called_once()


# -------------------------------------------------------------------------
# register_llm_evaluator helper
# -------------------------------------------------------------------------


def test_register_llm_evaluator_adds_to_registry() -> None:
    router = _make_router()
    registry = EvaluatorRegistry()
    ev = register_llm_evaluator(registry, router, "m")
    assert registry.get("llm_judge_v1") is ev


def test_register_llm_evaluator_returns_instance() -> None:
    router = _make_router()
    registry = EvaluatorRegistry()
    ev = register_llm_evaluator(registry, router, "judge-model")
    assert isinstance(ev, LLMEvaluator)
    assert ev.evaluator_id == "llm_judge_v1"


def test_register_llm_evaluator_can_set_as_default() -> None:
    router = _make_router()
    registry = EvaluatorRegistry()
    register_llm_evaluator(registry, router, "m")
    registry.set_default("llm_judge_v1")
    assert registry.get_default() is not None
    default = registry.get_default()
    assert default is not None
    assert default.evaluator_id == "llm_judge_v1"


# -------------------------------------------------------------------------
# config field
# -------------------------------------------------------------------------


def test_config_evaluation_judge_model_default() -> None:
    from agent33.config import Settings

    s = Settings()
    assert s.evaluation_judge_model == ""


def test_config_evaluation_judge_model_set() -> None:
    from agent33.config import Settings

    s = Settings(evaluation_judge_model="gpt-4o-mini")
    assert s.evaluation_judge_model == "gpt-4o-mini"
