"""Evaluator registry (P2.1).

Provides a central registry for ``Evaluator`` implementations, supporting
registration, lookup, and a configurable default evaluator.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent33.evaluation.evaluator_interface import Evaluator
    from agent33.evaluation.llm_evaluator import LLMEvaluator
    from agent33.llm.router import ModelRouter

logger = logging.getLogger(__name__)


class EvaluatorRegistry:
    """Registry that maps evaluator IDs to ``Evaluator`` instances.

    At most one evaluator may be designated as the *default*; it is returned
    by :meth:`get_default` and used when no explicit evaluator ID is
    specified.
    """

    def __init__(self) -> None:
        self._evaluators: dict[str, Evaluator] = {}
        self._default_id: str | None = None

    # -----------------------------------------------------------------------
    # Registration
    # -----------------------------------------------------------------------

    def register(self, evaluator: Evaluator) -> None:
        """Register an evaluator.  Overwrites any existing entry with the
        same ``evaluator_id``."""
        eid = evaluator.evaluator_id
        self._evaluators[eid] = evaluator
        logger.info("evaluator_registered evaluator_id=%s", eid)

    # -----------------------------------------------------------------------
    # Lookup
    # -----------------------------------------------------------------------

    def get(self, evaluator_id: str) -> Evaluator | None:
        """Return the evaluator with the given ID, or ``None``."""
        return self._evaluators.get(evaluator_id)

    def list_ids(self) -> list[str]:
        """Return a sorted list of all registered evaluator IDs."""
        return sorted(self._evaluators.keys())

    # -----------------------------------------------------------------------
    # Default management
    # -----------------------------------------------------------------------

    def get_default(self) -> Evaluator | None:
        """Return the current default evaluator, or ``None``."""
        if self._default_id is None:
            return None
        return self._evaluators.get(self._default_id)

    def set_default(self, evaluator_id: str) -> None:
        """Set the default evaluator by ID.

        Raises
        ------
        KeyError
            If no evaluator with ``evaluator_id`` is registered.
        """
        if evaluator_id not in self._evaluators:
            raise KeyError(f"Cannot set default: evaluator '{evaluator_id}' is not registered.")
        self._default_id = evaluator_id
        logger.info("evaluator_default_set evaluator_id=%s", evaluator_id)


# ---------------------------------------------------------------------------
# Module-level default registry
# ---------------------------------------------------------------------------


def _build_default_registry() -> EvaluatorRegistry:
    """Create a registry pre-populated with the rule-based evaluator."""
    from agent33.evaluation.rule_based_evaluator import RuleBasedEvaluator

    registry = EvaluatorRegistry()
    evaluator = RuleBasedEvaluator()
    registry.register(evaluator)
    registry.set_default(evaluator.evaluator_id)
    return registry


default_evaluator_registry: EvaluatorRegistry = _build_default_registry()


# ---------------------------------------------------------------------------
# LLM evaluator convenience registration (P2.2)
# ---------------------------------------------------------------------------


def register_llm_evaluator(
    registry: EvaluatorRegistry,
    model_router: ModelRouter,
    model: str,
) -> LLMEvaluator:
    """Register an :class:`~agent33.evaluation.llm_evaluator.LLMEvaluator`
    in *registry* and return the new instance.

    Parameters
    ----------
    registry:
        The target :class:`EvaluatorRegistry`.
    model_router:
        A configured ``ModelRouter`` instance.
    model:
        Model identifier for the LLM judge.
    """
    from agent33.evaluation.llm_evaluator import LLMEvaluator as _LLMEvaluator

    evaluator = _LLMEvaluator(model_router=model_router, model=model)
    registry.register(evaluator)
    return evaluator
