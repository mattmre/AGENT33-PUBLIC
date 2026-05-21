"""Inline Success Criteria (ISC) system for agent guardrails.

Provides composable criteria evaluation with support for anti-criteria
(things that should NOT be true), composite boolean logic, and coverage
checking against task constraints.

Inspired by CrewAI's GuardrailResult pattern, adapted for AGENT-33's
multi-agent architecture.
"""

from __future__ import annotations

import dataclasses
import logging
import os
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constraint-length heuristic
# ---------------------------------------------------------------------------

_CONSTRAINT_KEYWORDS = frozenset(
    {"must", "shall", "should", "never", "always", "ensure", "verify", "validate"}
)


def enforce_constraint_length(text: str) -> bool:
    """Check that *text* is a well-formed constraint (8-12 words with keyword).

    Returns ``True`` when the text contains 8-12 words *and* at least one
    recognised constraint keyword (must, shall, should, never, always,
    ensure, verify, validate).
    """
    words = text.split()
    if not (8 <= len(words) <= 12):
        return False
    lower_words = {w.lower().strip(".,;:!?") for w in words}
    return bool(lower_words & _CONSTRAINT_KEYWORDS)


# ---------------------------------------------------------------------------
# Core types
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class GuardrailResult:
    """Outcome of evaluating a single criterion or composite check."""

    success: bool
    result: Any = None
    error: str | None = None
    criterion_name: str = ""


class CompositeOperator(StrEnum):
    """Boolean operators for combining criteria."""

    AND = "and"
    OR = "or"


# ---------------------------------------------------------------------------
# Criterion classes
# ---------------------------------------------------------------------------


@dataclasses.dataclass(slots=True)
class ISCCriterion:
    """A single inline success criterion.

    Parameters
    ----------
    name:
        Human-readable label for the criterion.
    description:
        Short description of what the criterion checks.
    check_fn:
        Callable that takes a context dict and returns ``True`` when the
        criterion is satisfied.
    is_anti:
        If ``True`` the criterion is inverted — success means the check
        returned ``False``.
    """

    name: str
    description: str
    check_fn: Any  # Callable[[dict[str, Any]], bool]
    is_anti: bool = False
    criterion_id: str = dataclasses.field(default="")

    def __post_init__(self) -> None:
        if not self.criterion_id:
            self.criterion_id = f"isc-{os.urandom(6).hex()}"

    # -- Composition operators ------------------------------------------------

    def __and__(self, other: ISCCriterion | CompositeCriterion) -> CompositeCriterion:
        return CompositeCriterion(
            operator=CompositeOperator.AND,
            criteria=[self, other],
        )

    def __or__(self, other: ISCCriterion | CompositeCriterion) -> CompositeCriterion:
        return CompositeCriterion(
            operator=CompositeOperator.OR,
            criteria=[self, other],
        )


@dataclasses.dataclass(slots=True)
class CompositeCriterion:
    """Boolean combination of criteria."""

    operator: CompositeOperator
    criteria: list[ISCCriterion | CompositeCriterion]

    def evaluate(self, context: dict[str, Any]) -> GuardrailResult:
        """Evaluate all contained criteria using the configured operator."""
        results: list[GuardrailResult] = []
        for c in self.criteria:
            if isinstance(c, CompositeCriterion):
                results.append(c.evaluate(context))
            else:
                results.append(_evaluate_single(c, context))

        if self.operator == CompositeOperator.AND:
            success = all(r.success for r in results)
        else:
            success = any(r.success for r in results)

        failed = [r.criterion_name for r in results if not r.success]
        return GuardrailResult(
            success=success,
            result=results,
            error=f"Failed: {', '.join(failed)}" if failed and not success else None,
            criterion_name=f"composite_{self.operator.value}",
        )

    # -- Composition operators (allow chaining) --------------------------------

    def __and__(self, other: ISCCriterion | CompositeCriterion) -> CompositeCriterion:
        return CompositeCriterion(
            operator=CompositeOperator.AND,
            criteria=[self, other],
        )

    def __or__(self, other: ISCCriterion | CompositeCriterion) -> CompositeCriterion:
        return CompositeCriterion(
            operator=CompositeOperator.OR,
            criteria=[self, other],
        )


# ---------------------------------------------------------------------------
# Evaluation helpers
# ---------------------------------------------------------------------------


def _evaluate_single(criterion: ISCCriterion, context: dict[str, Any]) -> GuardrailResult:
    """Evaluate a single criterion, handling anti-criteria and exceptions."""
    try:
        raw = bool(criterion.check_fn(context))
    except Exception as exc:
        logger.warning("Criterion %s raised: %s", criterion.name, exc)
        return GuardrailResult(
            success=False,
            error=f"Exception: {exc}",
            criterion_name=criterion.name,
        )

    # Anti-criteria invert the result
    success = (not raw) if criterion.is_anti else raw
    return GuardrailResult(
        success=success,
        result=raw,
        criterion_name=criterion.name,
    )


# ---------------------------------------------------------------------------
# ISC Manager
# ---------------------------------------------------------------------------


class ISCManager:
    """Registry and evaluator for inline success criteria."""

    def __init__(self) -> None:
        self._criteria: dict[str, ISCCriterion] = {}

    # -- CRUD -----------------------------------------------------------------

    def add(self, criterion: ISCCriterion) -> None:
        """Register a criterion."""
        self._criteria[criterion.criterion_id] = criterion

    def remove(self, criterion_id: str) -> bool:
        """Remove a criterion by ID. Returns ``True`` if found."""
        return self._criteria.pop(criterion_id, None) is not None

    def get(self, criterion_id: str) -> ISCCriterion | None:
        """Retrieve a criterion by ID."""
        return self._criteria.get(criterion_id)

    def list_all(self) -> list[ISCCriterion]:
        """Return all registered criteria."""
        return list(self._criteria.values())

    # -- Evaluation -----------------------------------------------------------

    def evaluate_all(
        self,
        context: dict[str, Any],
        *,
        enable_anti_criteria: bool = True,
    ) -> list[GuardrailResult]:
        """Evaluate every registered criterion against *context*.

        When *enable_anti_criteria* is ``False``, anti-criteria are skipped.
        """
        results: list[GuardrailResult] = []
        for criterion in self._criteria.values():
            if criterion.is_anti and not enable_anti_criteria:
                continue
            results.append(_evaluate_single(criterion, context))
        return results

    def evaluate_composite(
        self,
        composite: CompositeCriterion,
        context: dict[str, Any],
    ) -> GuardrailResult:
        """Evaluate a composite criterion tree."""
        return composite.evaluate(context)

    # -- Coverage -------------------------------------------------------------

    def coverage_check(
        self,
        task_constraints: list[str],
    ) -> dict[str, str]:
        """Map task constraints to registered criteria names.

        Returns a dict ``{constraint: criterion_name}`` for constraints that
        have a matching criterion (case-insensitive substring match on name
        or description).  Unmatched constraints map to ``"unmapped"``.
        """
        result: dict[str, str] = {}
        criteria_list = self.list_all()

        for constraint in task_constraints:
            lower = constraint.lower()
            matched = False
            for c in criteria_list:
                if lower in c.name.lower() or lower in c.description.lower():
                    result[constraint] = c.name
                    matched = True
                    break
            if not matched:
                result[constraint] = "unmapped"
        return result
