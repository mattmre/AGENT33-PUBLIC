"""Action that validates data against a JSON schema or expression."""

from __future__ import annotations

from typing import Any

import structlog

from agent33.workflows.expressions import ExpressionEvaluator

logger = structlog.get_logger()


async def execute(
    inputs: dict[str, Any],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Validate data using either a JSON schema or an expression.

    Inputs should contain:
        - data: The data to validate.
        - schema: (optional) A JSON Schema dict to validate against.
        - expression: (optional) A Jinja2 expression that should evaluate truthy.

    At least one of schema or expression must be provided.

    Args:
        inputs: Contains data, schema, and/or expression.
        dry_run: If True, skip validation.

    Returns:
        A dict with valid (bool) and any errors.
    """
    data = inputs.get("data")
    schema = inputs.get("schema")
    expression = inputs.get("expression")

    logger.info("validate", has_schema=schema is not None, has_expression=expression is not None)

    if dry_run:
        return {"dry_run": True, "valid": True}

    errors: list[str] = []

    # JSON Schema validation
    if schema is not None:
        try:
            import jsonschema

            jsonschema.validate(instance=data, schema=schema)
        except ImportError:
            errors.append("jsonschema package not installed; cannot validate schema")
        except jsonschema.ValidationError as exc:
            errors.append(f"Schema validation failed: {exc.message}")

    # Expression-based validation
    if expression is not None:
        evaluator = ExpressionEvaluator()
        try:
            result = evaluator.evaluate_condition(expression, {"data": data, **inputs})
            if not result:
                errors.append(f"Expression evaluated to false: {expression}")
        except Exception as exc:
            errors.append(f"Expression evaluation error: {exc}")

    if not schema and not expression:
        errors.append("Validate action requires 'schema' or 'expression' in inputs")

    valid = len(errors) == 0
    logger.info("validate_complete", valid=valid, error_count=len(errors))

    if not valid:
        raise ValueError(f"Validation failed: {'; '.join(errors)}")

    return {"valid": True, "errors": errors}
