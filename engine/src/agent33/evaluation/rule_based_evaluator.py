"""Rule-based evaluator (P2.1).

A concrete ``Evaluator`` implementation that checks whether the actual
output contains all expected substrings.  This is the simplest evaluator
backend and serves as the default for the evaluation pipeline.
"""

from __future__ import annotations

import asyncio

from agent33.evaluation.evaluator_interface import (
    EvaluationInput,
    EvaluationResult,
    EvaluationVerdict,
)


class RuleBasedEvaluator:
    """Evaluator that uses substring matching against expected output.

    Behaviour
    ---------
    * If ``expected_output`` is ``None`` the verdict is **SKIP** with score
      ``0.5`` — the evaluator cannot make a determination without a reference.
    * Otherwise the expected output is split on newlines and each non-empty
      line is treated as a required substring of ``actual_output``.
    * The **score** equals the fraction of expected substrings found.
    * **PASS** when all expected substrings are present (score == 1.0);
      **FAIL** otherwise.
    """

    @property
    def evaluator_id(self) -> str:
        return "rule_based_v1"

    async def evaluate(self, eval_input: EvaluationInput) -> EvaluationResult:
        """Evaluate a single input via substring matching."""
        if eval_input.expected_output is None:
            return EvaluationResult(
                task_id=eval_input.task_id,
                verdict=EvaluationVerdict.SKIP,
                score=0.5,
                reason="No expected output provided; skipping evaluation.",
                evaluator_id=self.evaluator_id,
            )

        expected_lines = [line for line in eval_input.expected_output.split("\n") if line.strip()]

        if not expected_lines:
            # Empty expected output counts as a trivial pass.
            return EvaluationResult(
                task_id=eval_input.task_id,
                verdict=EvaluationVerdict.PASS,
                score=1.0,
                reason="Expected output is empty; trivially passing.",
                evaluator_id=self.evaluator_id,
            )

        matched = sum(1 for line in expected_lines if line in eval_input.actual_output)
        score = matched / len(expected_lines)

        if matched == len(expected_lines):
            verdict = EvaluationVerdict.PASS
            reason = f"All {len(expected_lines)} expected substrings found."
        else:
            missing = [line for line in expected_lines if line not in eval_input.actual_output]
            verdict = EvaluationVerdict.FAIL
            reason = (
                f"Matched {matched}/{len(expected_lines)} expected substrings. "
                f"Missing: {missing!r}"
            )

        return EvaluationResult(
            task_id=eval_input.task_id,
            verdict=verdict,
            score=score,
            reason=reason,
            evaluator_id=self.evaluator_id,
        )

    async def evaluate_batch(self, inputs: list[EvaluationInput]) -> list[EvaluationResult]:
        """Evaluate a batch of inputs concurrently."""
        return list(await asyncio.gather(*(self.evaluate(inp) for inp in inputs)))
