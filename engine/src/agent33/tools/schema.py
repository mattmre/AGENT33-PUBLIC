"""JSON Schema validation for tool parameters.

Validates tool input parameters against declared JSON Schemas,
supporting both :class:`SchemaAwareTool` protocol declarations
and :class:`ToolRegistryEntry` metadata schemas.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import jsonschema

if TYPE_CHECKING:
    from agent33.tools.base import Tool
    from agent33.tools.registry_entry import ToolRegistryEntry

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of parameter validation against a JSON Schema."""

    valid: bool
    errors: list[str]

    @staticmethod
    def ok() -> ValidationResult:
        return ValidationResult(valid=True, errors=[])

    @staticmethod
    def fail(errors: list[str]) -> ValidationResult:
        return ValidationResult(valid=False, errors=errors)


def validate_params(
    params: dict[str, Any],
    schema: dict[str, Any],
) -> ValidationResult:
    """Validate *params* against a JSON Schema.

    Returns a :class:`ValidationResult` with all validation errors.
    """
    if not schema:
        return ValidationResult.ok()

    validator_cls = jsonschema.Draft7Validator
    validator = validator_cls(schema)
    raw_errors = sorted(validator.iter_errors(params), key=lambda e: list(e.path))

    if not raw_errors:
        return ValidationResult.ok()

    errors: list[str] = []
    for error in raw_errors:
        path = ".".join(str(p) for p in error.absolute_path) if error.absolute_path else "<root>"
        errors.append(f"{path}: {error.message}")

    return ValidationResult.fail(errors)


def get_tool_schema(
    tool: Tool,
    entry: ToolRegistryEntry | None = None,
) -> dict[str, Any] | None:
    """Resolve the JSON Schema for a tool.

    Priority order:
    1. Schema from the ``ToolRegistryEntry.parameters_schema`` (if provided).
    2. Schema from the ``SchemaAwareTool.parameters_schema`` property.
    3. ``None`` if no schema is declared.
    """
    # Check registry entry first.
    if entry is not None and entry.parameters_schema:
        return entry.parameters_schema

    # Check if tool implements SchemaAwareTool.
    from agent33.tools.base import SchemaAwareTool

    if isinstance(tool, SchemaAwareTool):
        return tool.parameters_schema

    return None


def generate_tool_description(
    tool: Tool,
    entry: ToolRegistryEntry | None = None,
) -> dict[str, Any]:
    """Generate a tool description suitable for LLM function-calling.

    Returns a dict matching the OpenAI-style function schema format::

        {
            "name": "shell",
            "description": "Run a shell command...",
            "parameters": { ... JSON Schema ... }
        }
    """
    schema = get_tool_schema(tool, entry)
    result: dict[str, Any] = {
        "name": tool.name,
        "description": tool.description,
    }
    if schema is not None:
        result["parameters"] = schema
    return result
