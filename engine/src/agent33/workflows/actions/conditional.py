"""Action that evaluates a condition and branches execution."""

from __future__ import annotations

from typing import Any

import structlog

from agent33.workflows.expressions import ExpressionEvaluator

logger = structlog.get_logger()


async def execute(
    condition: str | None,
    inputs: dict[str, Any],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Evaluate a condition expression and return the branch to take.

    Args:
        condition: A Jinja2 expression to evaluate.
        inputs: Context variables for evaluation.
        dry_run: If True, return without evaluating.

    Returns:
        A dict with 'branch' set to 'then' or 'else', and 'condition_result'.
    """
    if not condition:
        raise ValueError("conditional action requires a 'condition' field")

    logger.info("conditional_evaluate", condition=condition)

    if dry_run:
        return {"dry_run": True, "branch": "then", "condition_result": True}

    evaluator = ExpressionEvaluator()
    result = evaluator.evaluate_condition(condition, inputs)

    branch = "then" if result else "else"
    logger.info("conditional_result", branch=branch, condition_result=result)

    return {"branch": branch, "condition_result": result}
