"""Base tool protocol and shared types."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from agent33.agents.events import ToolLoopEvent


@dataclasses.dataclass(frozen=True, slots=True)
class ToolContext:
    """Execution context passed to every tool invocation."""

    user_scopes: list[str] = dataclasses.field(default_factory=list)
    command_allowlist: list[str] = dataclasses.field(default_factory=list)
    path_allowlist: list[str] = dataclasses.field(default_factory=list)
    domain_allowlist: list[str] = dataclasses.field(default_factory=list)
    working_dir: Path = dataclasses.field(default_factory=Path.cwd)
    tool_policies: dict[str, str] = dataclasses.field(default_factory=dict)
    requested_by: str = ""
    tenant_id: str = ""
    session_id: str = ""
    event_sink: Callable[[ToolLoopEvent], Awaitable[None]] | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class ToolResult:
    """Result returned from a tool execution."""

    success: bool
    output: str = ""
    error: str = ""

    @staticmethod
    def ok(output: str = "") -> ToolResult:
        return ToolResult(success=True, output=output)

    @staticmethod
    def fail(error: str) -> ToolResult:
        return ToolResult(success=False, error=error)


@runtime_checkable
class Tool(Protocol):
    """Protocol that all tools must implement."""

    @property
    def name(self) -> str:
        """Unique tool identifier."""
        ...

    @property
    def description(self) -> str:
        """Human-readable description of what this tool does."""
        ...

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        """Run the tool with the given parameters and context."""
        ...


@runtime_checkable
class SchemaAwareTool(Tool, Protocol):
    """Extended tool protocol with JSON Schema parameter declaration.

    Tools that implement this protocol declare their expected input
    schema, enabling automatic validation before execution.
    """

    @property
    def parameters_schema(self) -> dict[str, Any]:
        """JSON Schema describing accepted parameters.

        Example::

            {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command to run"},
                    "timeout": {"type": "integer", "default": 30},
                },
                "required": ["command"],
            }
        """
        ...
