"""Programmatic Tool Calling (PTC) execution tool.

Allows the LLM to submit a Python script that calls tools via RPC,
collapsing multiple inference turns into a single script execution.

Phase 56 of the Hermes Adoption Roadmap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent33.execution.programmatic_tool_chain import PTCExecutor, validate_code_ast
from agent33.tools.base import ToolContext, ToolResult

if TYPE_CHECKING:
    from agent33.tools.registry import ToolRegistry


class PTCExecuteTool:
    """Execute an LLM-generated Python script with tool-calling via RPC.

    The script can import ``agent33_tools`` and call registered tools
    as regular Python functions.  Tool calls are dispatched through the
    parent process's tool registry over a TCP localhost socket.

    Implements the ``SchemaAwareTool`` protocol.
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        allowed_tools: list[str] | None = None,
        timeout_s: float = 300.0,
        max_calls: int = 50,
        max_stdout_bytes: int = 50 * 1024,
    ) -> None:
        self._executor = PTCExecutor(
            tool_registry=tool_registry,
            allowed_tools=allowed_tools,
            timeout_s=timeout_s,
            max_calls=max_calls,
            max_stdout_bytes=max_stdout_bytes,
        )

    @property
    def name(self) -> str:
        return "ptc_execute"

    @property
    def description(self) -> str:
        return (
            "Execute a Python script that can call tools programmatically. "
            "Import agent33_tools and call tool functions directly. "
            "Tool calls are dispatched through the tool registry. "
            "Use this to chain multiple tool calls in a single execution."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": (
                        "Python script to execute. The script can "
                        "'import agent33_tools' and call tool functions "
                        "like agent33_tools.shell(command='ls'). "
                        "Only stdout from the script is returned."
                    ),
                },
            },
            "required": ["code"],
        }

    async def execute(
        self,
        params: dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Validate and execute the submitted Python script.

        Parameters
        ----------
        params:
            code : str -- The Python script to execute.
        context:
            Passed through to tool calls made by the script.
        """
        code: str = params.get("code", "").strip()
        if not code:
            return ToolResult.fail("No code provided")

        # Pre-validate via AST before handing to the executor.
        try:
            violations = validate_code_ast(code)
        except SyntaxError as exc:
            return ToolResult.fail(f"Syntax error in script: {exc}")

        if violations:
            return ToolResult.fail(f"Code safety validation failed: {'; '.join(violations)}")

        result = await self._executor.execute(code, context=context)

        if not result.success:
            return ToolResult(
                success=False,
                output=result.stdout,
                error=result.error or result.stderr,
            )

        return ToolResult.ok(result.stdout)
