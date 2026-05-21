"""Optional live integration tests for LLM evaluator.

These tests are SKIPPED by default and only run when:
1. AGENT33_LLM_LIVE_TESTS=1 is set in the environment
2. A real LLM provider is configured (e.g., OPENAI_API_KEY or Ollama running)

They validate that the LLM evaluator produces structured JSON responses
from a real model and that the parsing pipeline works end-to-end.
"""

from __future__ import annotations

import os

import pytest

from agent33.evaluation.evaluator_interface import (
    EvaluationInput,
    EvaluationVerdict,
)
from agent33.evaluation.llm_evaluator import LLMEvaluator

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("AGENT33_LLM_LIVE_TESTS") != "1",
        reason="Live LLM tests disabled (set AGENT33_LLM_LIVE_TESTS=1 to enable)",
    ),
    pytest.mark.live,
]

# -------------------------------------------------------------------------
# Timeout for all live tests (seconds)
# -------------------------------------------------------------------------
_LIVE_TIMEOUT = 30


# -------------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------------


def _build_live_router():  # type: ignore[no-untyped-def]
    """Attempt to build a real ModelRouter from environment config.

    Returns the router and model name, or raises pytest.skip if no
    provider is available.
    """
    from agent33.config import Settings
    from agent33.llm.router import ModelRouter

    settings = Settings()

    model = settings.evaluation_judge_model
    if not model:
        # Fall back to ollama default if no judge model configured
        model = settings.ollama_default_model

    router = ModelRouter()

    # Try to register OpenAI provider if API key is available
    openai_key = settings.openai_api_key.get_secret_value()
    if openai_key:
        from agent33.llm.openai_provider import OpenAIProvider

        base_url = settings.openai_base_url or None
        provider = OpenAIProvider(api_key=openai_key, base_url=base_url)
        router.register("openai", provider)

    # Try to register Ollama provider (always available by default)
    try:
        from agent33.llm.ollama_provider import OllamaProvider

        ollama_provider = OllamaProvider(base_url=settings.ollama_base_url)
        router.register("ollama", ollama_provider)
    except Exception:  # noqa: BLE001
        pass

    # Check that we can route the chosen model
    try:
        router.route(model)
    except ValueError:
        pytest.skip(
            f"No provider registered that can serve model '{model}'. "
            "Ensure OPENAI_API_KEY is set or Ollama is running."
        )

    return router, model


@pytest.fixture(scope="module")
def live_evaluator():  # type: ignore[no-untyped-def]
    """Create a real LLMEvaluator backed by a live provider."""
    router, model = _build_live_router()
    return LLMEvaluator(model_router=router, model=model)


def _make_input(
    *,
    task_id: str = "live-t1",
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
# Core live evaluation
# -------------------------------------------------------------------------


@pytest.mark.timeout(_LIVE_TIMEOUT)
async def test_live_simple_pass_evaluation(live_evaluator: LLMEvaluator) -> None:
    """A trivially correct answer should produce a PASS verdict with high score."""
    inp = _make_input(
        task_id="live-simple-pass",
        prompt="What is the capital of France?",
        actual="Paris",
        expected="Paris",
    )
    result = await live_evaluator.evaluate(inp)

    # The model should return valid structured output
    assert result.task_id == "live-simple-pass"
    assert result.verdict in {
        EvaluationVerdict.PASS,
        EvaluationVerdict.FAIL,
        EvaluationVerdict.SKIP,
        EvaluationVerdict.ERROR,
    }
    assert 0.0 <= result.score <= 1.0
    assert isinstance(result.reason, str)
    assert result.evaluator_id == "llm_judge_v1"

    # For this trivially correct case, we expect PASS with high score
    assert result.verdict == EvaluationVerdict.PASS
    assert result.score >= 0.7


@pytest.mark.timeout(_LIVE_TIMEOUT)
async def test_live_clear_fail_evaluation(live_evaluator: LLMEvaluator) -> None:
    """A clearly wrong answer should produce a FAIL verdict."""
    inp = _make_input(
        task_id="live-clear-fail",
        prompt="What is the capital of France?",
        actual="Tokyo",
        expected="Paris",
    )
    result = await live_evaluator.evaluate(inp)

    assert result.task_id == "live-clear-fail"
    assert result.verdict == EvaluationVerdict.FAIL
    assert result.score < 0.7
    assert isinstance(result.reason, str)
    assert len(result.reason) > 0  # Model should explain why it failed


@pytest.mark.timeout(_LIVE_TIMEOUT)
async def test_live_skip_no_expected_output(live_evaluator: LLMEvaluator) -> None:
    """When expected_output is None, the evaluator skips without calling the LLM."""
    inp = _make_input(
        task_id="live-skip",
        prompt="Generate something creative",
        actual="A beautiful sunset",
        expected=None,
    )
    result = await live_evaluator.evaluate(inp)

    assert result.task_id == "live-skip"
    assert result.verdict == EvaluationVerdict.SKIP
    assert result.score == 0.5


@pytest.mark.timeout(_LIVE_TIMEOUT)
async def test_live_response_is_valid_json_structure(live_evaluator: LLMEvaluator) -> None:
    """The end-to-end parse pipeline produces all required result fields."""
    inp = _make_input(
        task_id="live-structure",
        prompt="Summarize: The cat sat on the mat.",
        actual="A cat sits on a mat.",
        expected="A cat is sitting on a mat.",
    )
    result = await live_evaluator.evaluate(inp)

    # Verify all fields are populated with correct types
    assert isinstance(result.task_id, str)
    assert isinstance(result.verdict, EvaluationVerdict)
    assert isinstance(result.score, float)
    assert isinstance(result.reason, str)
    assert isinstance(result.evaluator_id, str)
    assert result.evaluator_id == "llm_judge_v1"
    # Score is always clamped [0, 1]
    assert 0.0 <= result.score <= 1.0


# -------------------------------------------------------------------------
# Edge cases
# -------------------------------------------------------------------------


@pytest.mark.timeout(_LIVE_TIMEOUT)
async def test_live_empty_actual_output(live_evaluator: LLMEvaluator) -> None:
    """Empty actual output should still produce a structured result (likely FAIL)."""
    inp = _make_input(
        task_id="live-empty-actual",
        prompt="What is 2+2?",
        actual="",
        expected="4",
    )
    result = await live_evaluator.evaluate(inp)

    assert result.task_id == "live-empty-actual"
    # Empty actual output is incorrect -- should fail
    assert result.verdict in {EvaluationVerdict.FAIL, EvaluationVerdict.ERROR}
    assert 0.0 <= result.score <= 1.0


@pytest.mark.timeout(_LIVE_TIMEOUT)
async def test_live_long_input_text(live_evaluator: LLMEvaluator) -> None:
    """Very long input should not cause the evaluator to crash or hang."""
    long_text = "The quick brown fox jumps over the lazy dog. " * 200  # ~9000 chars
    inp = _make_input(
        task_id="live-long-input",
        prompt="Summarize the following text: " + long_text[:2000],
        actual=long_text[:1000],
        expected="A summary of repeated sentences about a fox and a dog.",
    )
    result = await live_evaluator.evaluate(inp)

    assert result.task_id == "live-long-input"
    assert result.verdict in {
        EvaluationVerdict.PASS,
        EvaluationVerdict.FAIL,
        EvaluationVerdict.SKIP,
        EvaluationVerdict.ERROR,
    }
    assert 0.0 <= result.score <= 1.0


# -------------------------------------------------------------------------
# Batch evaluation
# -------------------------------------------------------------------------


@pytest.mark.timeout(_LIVE_TIMEOUT * 3)  # batch may take longer
async def test_live_batch_evaluation(live_evaluator: LLMEvaluator) -> None:
    """Batch evaluation should return results for all inputs in order."""
    inputs = [
        _make_input(
            task_id="live-batch-1",
            prompt="What is 1+1?",
            actual="2",
            expected="2",
        ),
        _make_input(
            task_id="live-batch-2",
            prompt="What is the color of the sky?",
            actual="Green",
            expected="Blue",
        ),
        _make_input(
            task_id="live-batch-3",
            prompt="Something open-ended",
            actual="Anything",
            expected=None,
        ),
    ]
    results = await live_evaluator.evaluate_batch(inputs)

    assert len(results) == 3
    assert results[0].task_id == "live-batch-1"
    assert results[1].task_id == "live-batch-2"
    assert results[2].task_id == "live-batch-3"

    # First should pass (trivially correct)
    assert results[0].verdict == EvaluationVerdict.PASS

    # Second should fail (wrong color)
    assert results[1].verdict == EvaluationVerdict.FAIL

    # Third should skip (no expected output)
    assert results[2].verdict == EvaluationVerdict.SKIP
