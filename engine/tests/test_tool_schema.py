"""Tests for JSON Schema validation on the tool protocol.

Tests cover: schema validation logic, SchemaAwareTool detection,
registry validated_execute, schema resolution priority, and
LLM-ready tool description generation.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent33.tools.base import SchemaAwareTool, Tool, ToolContext, ToolResult
from agent33.tools.registry import ToolRegistry
from agent33.tools.registry_entry import ToolRegistryEntry
from agent33.tools.schema import (
    generate_tool_description,
    get_tool_schema,
    validate_params,
)

# ── Test fixtures ────────────────────────────────────────────────────


class _PlainTool:
    """A basic tool without schema declaration."""

    @property
    def name(self) -> str:
        return "plain"

    @property
    def description(self) -> str:
        return "A plain tool with no schema."

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult.ok(f"plain: {params.get('value', '')}")


class _SchemaToolGreeter:
    """A tool that declares its parameters_schema."""

    @property
    def name(self) -> str:
        return "greeter"

    @property
    def description(self) -> str:
        return "Greet someone by name."

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Person to greet"},
                "times": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 1,
                },
            },
            "required": ["name"],
        }

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        name = params.get("name", "world")
        times = params.get("times", 1)
        return ToolResult.ok(f"Hello, {name}! " * times)


_SAMPLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "format": "uri"},
        "method": {"type": "string", "enum": ["GET", "POST"]},
    },
    "required": ["url"],
}


# ═══════════════════════════════════════════════════════════════════════
# Validation Tests
# ═══════════════════════════════════════════════════════════════════════


class TestValidateParams:
    """Test the validate_params function."""

    def test_valid_params(self) -> None:
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        result = validate_params({"name": "Alice"}, schema)
        assert result.valid
        assert result.errors == []

    def test_missing_required(self) -> None:
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        result = validate_params({}, schema)
        assert not result.valid
        assert any("name" in e for e in result.errors)

    def test_wrong_type(self) -> None:
        schema = {
            "type": "object",
            "properties": {"count": {"type": "integer"}},
        }
        result = validate_params({"count": "not-a-number"}, schema)
        assert not result.valid
        assert any("integer" in e.lower() for e in result.errors)

    def test_enum_violation(self) -> None:
        schema = {
            "type": "object",
            "properties": {"method": {"type": "string", "enum": ["GET", "POST"]}},
        }
        result = validate_params({"method": "DELETE"}, schema)
        assert not result.valid

    def test_minimum_violation(self) -> None:
        schema = {
            "type": "object",
            "properties": {"timeout": {"type": "integer", "minimum": 1}},
        }
        result = validate_params({"timeout": 0}, schema)
        assert not result.valid

    def test_empty_schema_always_valid(self) -> None:
        result = validate_params({"anything": "goes"}, {})
        assert result.valid

    def test_multiple_errors(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name", "age"],
        }
        result = validate_params({}, schema)
        assert not result.valid
        assert len(result.errors) >= 2

    def test_nested_property_error(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "config": {
                    "type": "object",
                    "properties": {"port": {"type": "integer"}},
                },
            },
        }
        result = validate_params({"config": {"port": "not-int"}}, schema)
        assert not result.valid
        assert any("config" in e or "port" in e for e in result.errors)

    def test_additional_properties_allowed_by_default(self) -> None:
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }
        result = validate_params({"name": "Alice", "extra": True}, schema)
        assert result.valid

    def test_additional_properties_forbidden(self) -> None:
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "additionalProperties": False,
        }
        result = validate_params({"name": "Alice", "extra": True}, schema)
        assert not result.valid


# ═══════════════════════════════════════════════════════════════════════
# Protocol Detection Tests
# ═══════════════════════════════════════════════════════════════════════


class TestSchemaAwareToolProtocol:
    """Test SchemaAwareTool protocol detection."""

    def test_plain_tool_is_tool(self) -> None:
        tool = _PlainTool()
        assert isinstance(tool, Tool)

    def test_plain_tool_not_schema_aware(self) -> None:
        tool = _PlainTool()
        assert not isinstance(tool, SchemaAwareTool)

    def test_schema_tool_is_tool(self) -> None:
        tool = _SchemaToolGreeter()
        assert isinstance(tool, Tool)

    def test_schema_tool_is_schema_aware(self) -> None:
        tool = _SchemaToolGreeter()
        assert isinstance(tool, SchemaAwareTool)

    def test_schema_tool_has_schema(self) -> None:
        tool = _SchemaToolGreeter()
        schema = tool.parameters_schema
        assert schema["type"] == "object"
        assert "name" in schema["properties"]
        assert "name" in schema["required"]


# ═══════════════════════════════════════════════════════════════════════
# Schema Resolution Tests
# ═══════════════════════════════════════════════════════════════════════


class TestGetToolSchema:
    """Test schema resolution priority."""

    def test_no_schema(self) -> None:
        tool = _PlainTool()
        assert get_tool_schema(tool) is None

    def test_from_tool(self) -> None:
        tool = _SchemaToolGreeter()
        schema = get_tool_schema(tool)
        assert schema is not None
        assert schema["type"] == "object"

    def test_entry_overrides_tool(self) -> None:
        tool = _SchemaToolGreeter()
        entry = ToolRegistryEntry(
            tool_id="greeter",
            name="greeter",
            version="1.0",
            parameters_schema=_SAMPLE_SCHEMA,
        )
        schema = get_tool_schema(tool, entry)
        # Entry schema takes precedence.
        assert schema == _SAMPLE_SCHEMA
        assert "url" in schema["properties"]

    def test_entry_with_empty_schema_falls_through(self) -> None:
        tool = _SchemaToolGreeter()
        entry = ToolRegistryEntry(
            tool_id="greeter",
            name="greeter",
            version="1.0",
            parameters_schema={},
        )
        schema = get_tool_schema(tool, entry)
        # Empty entry schema → falls through to tool schema.
        assert schema is not None
        assert "name" in schema["properties"]


# ═══════════════════════════════════════════════════════════════════════
# Tool Description Generation Tests
# ═══════════════════════════════════════════════════════════════════════


class TestGenerateToolDescription:
    """Test LLM-ready tool description generation."""

    def test_plain_tool_no_parameters(self) -> None:
        tool = _PlainTool()
        desc = generate_tool_description(tool)
        assert desc["name"] == "plain"
        assert desc["description"] == "A plain tool with no schema."
        assert "parameters" not in desc

    def test_schema_tool_has_parameters(self) -> None:
        tool = _SchemaToolGreeter()
        desc = generate_tool_description(tool)
        assert desc["name"] == "greeter"
        assert "parameters" in desc
        assert desc["parameters"]["type"] == "object"
        assert "name" in desc["parameters"]["properties"]

    def test_entry_schema_in_description(self) -> None:
        tool = _PlainTool()
        entry = ToolRegistryEntry(
            tool_id="plain",
            name="plain",
            version="1.0",
            parameters_schema=_SAMPLE_SCHEMA,
        )
        desc = generate_tool_description(tool, entry)
        assert "parameters" in desc
        assert "url" in desc["parameters"]["properties"]


# ═══════════════════════════════════════════════════════════════════════
# Registry Validated Execution Tests
# ═══════════════════════════════════════════════════════════════════════


class TestRegistryValidatedExecute:
    """Test ToolRegistry.validated_execute."""

    @pytest.mark.asyncio
    async def test_valid_params_execute(self) -> None:
        registry = ToolRegistry()
        registry.register(_SchemaToolGreeter())
        ctx = ToolContext()
        result = await registry.validated_execute("greeter", {"name": "Alice"}, ctx)
        assert result.success
        assert "Hello, Alice!" in result.output

    @pytest.mark.asyncio
    async def test_invalid_params_rejected(self) -> None:
        registry = ToolRegistry()
        registry.register(_SchemaToolGreeter())
        ctx = ToolContext()
        # Missing required "name" param.
        result = await registry.validated_execute("greeter", {}, ctx)
        assert not result.success
        assert "validation failed" in result.error.lower()

    @pytest.mark.asyncio
    async def test_wrong_type_rejected(self) -> None:
        registry = ToolRegistry()
        registry.register(_SchemaToolGreeter())
        ctx = ToolContext()
        result = await registry.validated_execute(
            "greeter", {"name": "Alice", "times": "not-int"}, ctx
        )
        assert not result.success
        assert "validation failed" in result.error.lower()

    @pytest.mark.asyncio
    async def test_minimum_violation_rejected(self) -> None:
        registry = ToolRegistry()
        registry.register(_SchemaToolGreeter())
        ctx = ToolContext()
        result = await registry.validated_execute("greeter", {"name": "Alice", "times": 0}, ctx)
        assert not result.success

    @pytest.mark.asyncio
    async def test_unknown_tool_fails(self) -> None:
        registry = ToolRegistry()
        ctx = ToolContext()
        result = await registry.validated_execute("nonexistent", {}, ctx)
        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_plain_tool_no_validation(self) -> None:
        """Plain tools without schema skip validation and execute normally."""
        registry = ToolRegistry()
        registry.register(_PlainTool())
        ctx = ToolContext()
        result = await registry.validated_execute("plain", {"value": "anything"}, ctx)
        assert result.success
        assert "plain: anything" in result.output

    @pytest.mark.asyncio
    async def test_entry_schema_used_for_validation(self) -> None:
        """Registry entry schema takes precedence for validation."""
        registry = ToolRegistry()
        tool = _PlainTool()
        entry = ToolRegistryEntry(
            tool_id="plain",
            name="plain",
            version="1.0",
            parameters_schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
        )
        registry.register_with_entry(tool, entry)
        ctx = ToolContext()

        # Valid call succeeds.
        result = await registry.validated_execute("plain", {"value": "ok"}, ctx)
        assert result.success

        # Missing required "value" fails.
        result = await registry.validated_execute("plain", {}, ctx)
        assert not result.success
        assert "validation failed" in result.error.lower()


# ═══════════════════════════════════════════════════════════════════════
# Registry Entry Schema Field Tests
# ═══════════════════════════════════════════════════════════════════════


class TestRegistryEntrySchemaField:
    """Test ToolRegistryEntry.parameters_schema field."""

    def test_default_empty(self) -> None:
        entry = ToolRegistryEntry(tool_id="test", name="test", version="1.0")
        assert entry.parameters_schema == {}
        assert entry.result_schema == {}

    def test_schema_stored(self) -> None:
        entry = ToolRegistryEntry(
            tool_id="test",
            name="test",
            version="1.0",
            parameters_schema=_SAMPLE_SCHEMA,
        )
        assert entry.parameters_schema["type"] == "object"
        assert "url" in entry.parameters_schema["properties"]

    def test_serialization_roundtrip(self) -> None:
        entry = ToolRegistryEntry(
            tool_id="test",
            name="test",
            version="1.0",
            parameters_schema=_SAMPLE_SCHEMA,
        )
        data = entry.model_dump(mode="json")
        restored = ToolRegistryEntry.model_validate(data)
        assert restored.parameters_schema == _SAMPLE_SCHEMA


# ═══════════════════════════════════════════════════════════════════════
# Builtin Tool Schema Tests
# ═══════════════════════════════════════════════════════════════════════


class TestBuiltinToolSchemas:
    """Test that builtin tools declare valid schemas."""

    def test_shell_tool_schema(self) -> None:
        from agent33.tools.builtin.shell import ShellTool

        tool = ShellTool()
        assert isinstance(tool, SchemaAwareTool)
        schema = tool.parameters_schema
        assert schema["type"] == "object"
        assert "command" in schema["required"]
        assert schema["properties"]["command"]["type"] == "string"

    def test_file_ops_tool_schema(self) -> None:
        from agent33.tools.builtin.file_ops import FileOpsTool

        tool = FileOpsTool()
        assert isinstance(tool, SchemaAwareTool)
        schema = tool.parameters_schema
        assert "operation" in schema["required"]
        assert "path" in schema["required"]
        assert schema["properties"]["operation"]["enum"] == ["read", "write", "list"]

    def test_shell_schema_validates_correct_params(self) -> None:
        from agent33.tools.builtin.shell import ShellTool

        tool = ShellTool()
        result = validate_params(
            {"command": "echo hello", "timeout": 10},
            tool.parameters_schema,
        )
        assert result.valid

    def test_shell_schema_rejects_missing_command(self) -> None:
        from agent33.tools.builtin.shell import ShellTool

        tool = ShellTool()
        result = validate_params({}, tool.parameters_schema)
        assert not result.valid

    def test_shell_schema_rejects_bad_timeout(self) -> None:
        from agent33.tools.builtin.shell import ShellTool

        tool = ShellTool()
        result = validate_params(
            {"command": "echo", "timeout": 0},
            tool.parameters_schema,
        )
        assert not result.valid
