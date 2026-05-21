"""Evaluation suite, regression gates, and golden task framework."""

from agent33.evaluation.evaluator_interface import (
    EvaluationInput,
    EvaluationResult,
    EvaluationVerdict,
    Evaluator,
)
from agent33.evaluation.evaluator_registry import (
    EvaluatorRegistry,
    default_evaluator_registry,
)
from agent33.evaluation.rule_based_evaluator import RuleBasedEvaluator

__all__ = [
    "Evaluator",
    "EvaluationInput",
    "EvaluationResult",
    "EvaluationVerdict",
    "EvaluatorRegistry",
    "RuleBasedEvaluator",
    "default_evaluator_registry",
]
