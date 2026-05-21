"""Evaluator interface abstraction (P2.1).

Defines the ``Evaluator`` protocol and supporting data types that allow
swappable evaluator backends (rule-based, LLM-backed, hybrid) for the
evaluation pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class EvaluationVerdict(StrEnum):
    """Verdict produced by an evaluator for a single evaluation input."""

    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class EvaluationInput:
    """Input payload for a single evaluation.

    Parameters
    ----------
    task_id:
        Unique identifier for the evaluation task.
    prompt:
        The original prompt / instruction given to the system under test.
    actual_output:
        The actual output produced by the system.
    expected_output:
        The expected / reference output, if available.  ``None`` indicates
        that no reference is available and the evaluator may choose to SKIP.
    metadata:
        Arbitrary key-value metadata carried through the evaluation.
    """

    task_id: str
    prompt: str
    actual_output: str
    expected_output: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class EvaluationResult:
    """Result produced by an evaluator for a single evaluation input.

    Parameters
    ----------
    task_id:
        Identifier of the evaluated task (matches ``EvaluationInput.task_id``).
    verdict:
        Pass / fail / skip / error verdict.
    score:
        Numeric score in the range ``[0.0, 1.0]``.
    reason:
        Human-readable explanation of the verdict.
    evaluator_id:
        Identifier of the evaluator that produced this result.
    metadata:
        Arbitrary key-value metadata produced during evaluation.
    """

    task_id: str
    verdict: EvaluationVerdict
    score: float
    reason: str
    evaluator_id: str
    metadata: dict[str, object] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class Evaluator(Protocol):
    """Protocol for pluggable evaluator backends.

    Any class that implements this protocol can be registered in the
    ``EvaluatorRegistry`` and used as a drop-in evaluation backend.
    """

    @property
    def evaluator_id(self) -> str:
        """Stable identifier for this evaluator (e.g. ``rule_based_v1``)."""
        ...  # pragma: no cover

    async def evaluate(self, eval_input: EvaluationInput) -> EvaluationResult:
        """Evaluate a single input and return a result."""
        ...  # pragma: no cover

    async def evaluate_batch(self, inputs: list[EvaluationInput]) -> list[EvaluationResult]:
        """Evaluate a batch of inputs and return results in the same order."""
        ...  # pragma: no cover
