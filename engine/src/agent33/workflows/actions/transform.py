"""Action that transforms data using Jinja2 expressions."""

from __future__ import annotations

from typing import Any

import structlog

from agent33.workflows.expressions import ExpressionEvaluator

logger = structlog.get_logger()


async def execute(
    inputs: dict[str, Any],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Transform data by evaluating Jinja2 template expressions.

    Inputs should contain:
        - template: A dict where string values are Jinja2 expressions evaluated
          against the full inputs context.
        OR
        - expression: A single Jinja2 expression whose result is returned as "result".
        - data: The source data available as 'data' in the expression context.

    Args:
        inputs: Contains template or expression plus source data.
        dry_run: If True, skip transformation.

    Returns:
        A dict with the transformed data.
    """
    logger.info("transform")

    if dry_run:
        return {"dry_run": True, "inputs": inputs}

    evaluator = ExpressionEvaluator()
    context = dict(inputs)

    template = inputs.get("template")
    expression = inputs.get("expression")

    if template is not None and isinstance(template, dict):
        result = evaluator.resolve_inputs(template, context)
        logger.info("transform_complete", output_keys=list(result.keys()))
        return result

    if expression is not None:
        result_value = evaluator.evaluate(str(expression), context)
        logger.info("transform_complete", result_type=type(result_value).__name__)
        return {"result": result_value}

    # If neither template nor expression, pass through data
    data = inputs.get("data")
    if data is not None:
        return {"result": data}

    return dict(inputs)
