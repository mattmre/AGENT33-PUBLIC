"""Expression evaluator using Jinja2 sandboxed environment."""

from __future__ import annotations

import json
from typing import Any

from jinja2.sandbox import SandboxedEnvironment


class ExpressionEvaluator:
    """Evaluates expressions within a sandboxed Jinja2 environment.

    Supports both template rendering (strings containing {{ }}) and
    direct expression evaluation (plain expressions returned as native types).
    """

    def __init__(self) -> None:
        self._env = SandboxedEnvironment()
        # Register useful filters
        self._env.filters["tojson"] = json.dumps
        self._env.filters["fromjson"] = json.loads
        self._env.globals["range"] = range
        self._env.globals["len"] = len
        self._env.globals["str"] = str
        self._env.globals["int"] = int
        self._env.globals["float"] = float
        self._env.globals["bool"] = bool
        self._env.globals["list"] = list
        self._env.globals["dict"] = dict

    def evaluate(self, expression: str, context: dict[str, Any]) -> Any:
        """Evaluate an expression or template string against the given context.

        If the expression contains Jinja2 delimiters ({{ or {%), it is
        rendered as a template and the resulting string is returned.

        Otherwise, the expression is evaluated as a Jinja2 expression and
        the native Python value is returned (bool, int, string, etc.).

        Args:
            expression: A Jinja2 expression or template string.
            context: Variables available during evaluation.

        Returns:
            The evaluated result.
        """
        stripped = expression.strip()

        # If it looks like a template string, render it
        if "{{" in stripped or "{%" in stripped:
            template = self._env.from_string(stripped)
            return template.render(**context)

        # Otherwise, compile as a Jinja2 expression and return native value
        expr = self._env.compile_expression(stripped)
        return expr(**context)

    def evaluate_condition(self, condition: str, context: dict[str, Any]) -> bool:
        """Evaluate a condition expression and return a boolean.

        Args:
            condition: A Jinja2 expression expected to evaluate to a truthy value.
            context: Variables available during evaluation.

        Returns:
            True if the condition is truthy, False otherwise.
        """
        result = self.evaluate(condition, context)
        return bool(result)

    def render_template(self, template_str: str, context: dict[str, Any]) -> str:
        """Render a Jinja2 template string.

        Args:
            template_str: A string potentially containing {{ }} blocks.
            context: Variables available during rendering.

        Returns:
            The rendered string.
        """
        template = self._env.from_string(template_str)
        return template.render(**context)

    def resolve_inputs(self, inputs: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """Resolve a mapping of input values, evaluating any string expressions.

        Args:
            inputs: A dict whose string values may be Jinja2 expressions.
            context: Variables available during evaluation.

        Returns:
            A new dict with all string values evaluated.
        """
        resolved: dict[str, Any] = {}
        for key, value in inputs.items():
            if isinstance(value, str):
                resolved[key] = self.evaluate(value, context)
            elif isinstance(value, dict):
                resolved[key] = self.resolve_inputs(value, context)
            elif isinstance(value, list):
                resolved[key] = [
                    self.evaluate(v, context) if isinstance(v, str) else v for v in value
                ]
            else:
                resolved[key] = value
        return resolved
