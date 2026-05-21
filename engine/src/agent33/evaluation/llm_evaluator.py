"""LLM-backed evaluator (P2.2).

Provides an ``LLMEvaluator`` that calls a language model through the
existing ``ModelRouter`` to judge evaluation inputs.  This is the first
real LLM judge backend for the evaluation pipeline.

CI safety
---------
The ``LLMEvaluator`` never makes live provider calls in tests --- callers
must pass a mocked ``ModelRouter``.  When ``evaluation_judge_model`` is
empty the evaluator should not be instantiated (the caller checks config).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from agent33.evaluation.evaluator_interface import (
    EvaluationInput,
    EvaluationResult,
    EvaluationVerdict,
)

if TYPE_CHECKING:
    from agent33.llm.router import ModelRouter

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are an evaluation judge. Given a task ID, a prompt, the actual output \
from a system under test, and an expected reference output, decide whether \
the actual output satisfies the requirement.

Respond ONLY with valid JSON in exactly this format --- no markdown fences, no \
extra keys:
{"verdict": "pass" | "fail" | "skip", "score": <float 0.0-1.0>, \
"reason": "<short explanation>"}

Guidelines:
- "pass"  score >= 0.7 : actual output substantially meets the expectation
- "fail"  score < 0.7 : actual output does not meet the expectation
- "skip"  score 0.5   : use ONLY when expected output is "(none)" and \
evaluation is impossible without a reference
"""

_USER_TEMPLATE = """\
Task ID: {task_id}
Prompt: {prompt}
Actual output: {actual_output}
Expected output: {expected_output}
"""


class LLMEvaluator:
    """Evaluator that uses a language model as the judge backend.

    Parameters
    ----------
    model_router:
        Configured :class:`~agent33.llm.router.ModelRouter` instance.
    model:
        Model identifier to pass to ``model_router.complete()``.
    """

    def __init__(self, model_router: ModelRouter, model: str) -> None:
        if not model:
            raise ValueError("LLMEvaluator requires a non-empty model identifier.")
        self._router = model_router
        self._model = model

    # ------------------------------------------------------------------
    # Evaluator protocol
    # ------------------------------------------------------------------

    @property
    def evaluator_id(self) -> str:
        return "llm_judge_v1"

    async def evaluate(self, eval_input: EvaluationInput) -> EvaluationResult:
        """Evaluate a single input using the LLM judge."""
        if eval_input.expected_output is None:
            return EvaluationResult(
                task_id=eval_input.task_id,
                verdict=EvaluationVerdict.SKIP,
                score=0.5,
                reason="No expected output provided; skipping LLM evaluation.",
                evaluator_id=self.evaluator_id,
            )

        from agent33.llm.base import ChatMessage

        messages = [
            ChatMessage(role="system", content=_SYSTEM_PROMPT),
            ChatMessage(
                role="user",
                content=_USER_TEMPLATE.format(
                    task_id=eval_input.task_id,
                    prompt=eval_input.prompt,
                    actual_output=eval_input.actual_output,
                    expected_output=eval_input.expected_output,
                ),
            ),
        ]

        try:
            response = await self._router.complete(
                messages,
                model=self._model,
                temperature=0.0,
                max_tokens=256,
            )
            raw = response.content.strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "llm_evaluator_provider_error task_id=%s error=%s",
                eval_input.task_id,
                exc,
            )
            return EvaluationResult(
                task_id=eval_input.task_id,
                verdict=EvaluationVerdict.ERROR,
                score=0.0,
                reason=f"LLM provider error: {exc}",
                evaluator_id=self.evaluator_id,
            )

        return self._parse_response(eval_input.task_id, raw)

    async def evaluate_batch(self, inputs: list[EvaluationInput]) -> list[EvaluationResult]:
        """Evaluate a batch of inputs concurrently."""
        return list(await asyncio.gather(*(self.evaluate(inp) for inp in inputs)))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_response(self, task_id: str, raw: str) -> EvaluationResult:
        """Parse the JSON verdict returned by the LLM."""
        # Strip optional markdown code fences that some LLMs add despite the prompt
        if raw.startswith("```"):
            lines = raw.splitlines()
            # drop first line (```json or ```) and last line (```)
            inner = lines[1:-1] if len(lines) > 2 else lines[1:]
            raw = "\n".join(inner).strip()

        try:
            data: dict[str, Any] = json.loads(raw)
            if not isinstance(data, dict):
                return EvaluationResult(
                    task_id=task_id,
                    verdict=EvaluationVerdict.ERROR,
                    score=0.0,
                    reason=f"LLM returned {type(data).__name__} instead of JSON object",
                    evaluator_id=self.evaluator_id,
                )
            verdict_str = str(data.get("verdict", "")).lower()
            score = float(data.get("score", 0.0))
            reason = str(data.get("reason", ""))

            try:
                verdict = EvaluationVerdict(verdict_str)
            except ValueError:
                verdict = EvaluationVerdict.ERROR
                reason = f"Unknown verdict value '{verdict_str}'; original reason: {reason}"

            score = max(0.0, min(1.0, score))  # clamp to [0, 1]

        except (json.JSONDecodeError, TypeError, ValueError, AttributeError) as exc:
            logger.warning(
                "llm_evaluator_parse_error task_id=%s raw=%r error=%s",
                task_id,
                raw[:120],
                exc,
            )
            return EvaluationResult(
                task_id=task_id,
                verdict=EvaluationVerdict.ERROR,
                score=0.0,
                reason=f"Failed to parse LLM response as JSON: {exc}",
                evaluator_id=self.evaluator_id,
            )

        return EvaluationResult(
            task_id=task_id,
            verdict=verdict,
            score=score,
            reason=reason,
            evaluator_id=self.evaluator_id,
        )
