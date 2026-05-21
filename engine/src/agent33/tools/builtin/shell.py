"""Shell command execution tool."""

from __future__ import annotations

import asyncio
import re
import shlex
from typing import Any

from agent33.tools.base import ToolContext, ToolResult

_DEFAULT_TIMEOUT = 30

# Patterns that indicate command chaining / subshell injection
_SUBSHELL_PATTERNS = re.compile(r"\$\(|`")
_CHAIN_OPERATORS = re.compile(r"\s*([|;&]|&&|\|\|)\s*")


class ShellTool:
    """Execute shell commands with allowlist enforcement and timeout."""

    @property
    def name(self) -> str:
        return "shell"

    @property
    def description(self) -> str:
        return "Run a shell command and capture its output."

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Maximum seconds to wait (default 30).",
                    "default": 30,
                    "minimum": 1,
                },
            },
            "required": ["command"],
        }

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        """Run a shell command.

        Parameters
        ----------
        params:
            command : str  - The command string to execute.
            timeout : int  - Max seconds to wait (default 30).
        context:
            command_allowlist and working_dir are respected.
        """
        command: str = params.get("command", "").strip()
        if not command:
            return ToolResult.fail("No command provided")

        timeout: int = params.get("timeout", _DEFAULT_TIMEOUT)

        # Block subshell injection ($(...) and backticks)
        if _SUBSHELL_PATTERNS.search(command):
            return ToolResult.fail("Subshell patterns ($() and backticks) are not allowed")

        # Multi-segment validation: split on chain operators and validate each segment
        try:
            segments = _CHAIN_OPERATORS.split(command)
        except re.error:
            return ToolResult.fail("Invalid command syntax")

        executables: list[str] = []
        for segment in segments:
            segment = segment.strip()
            if not segment or segment in ("|", "&", ";", "&&", "||"):
                continue
            try:
                parts = shlex.split(segment)
            except ValueError as exc:
                return ToolResult.fail(f"Invalid command syntax: {exc}")
            if parts:
                executables.append(parts[0])

        if not executables:
            return ToolResult.fail("No executable found in command")

        # Validate ALL executables against allowlist (not just the first one)
        if context.command_allowlist:
            for executable in executables:
                if executable not in context.command_allowlist:
                    return ToolResult.fail(
                        f"Command '{executable}' is not in the allowlist. "
                        f"Allowed: {', '.join(context.command_allowlist)}"
                    )

        # Use only the first executable for subprocess (we pass full command
        # through shlex.split for proper handling)
        try:
            parts = shlex.split(command)
        except ValueError as exc:
            return ToolResult.fail(f"Invalid command syntax: {exc}")

        try:
            proc = await asyncio.create_subprocess_exec(
                *parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(context.working_dir),
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            return ToolResult.fail(f"Command timed out after {timeout}s")
        except FileNotFoundError:
            return ToolResult.fail(f"Command not found: {executables[0]}")
        except OSError as exc:
            return ToolResult.fail(f"OS error: {exc}")

        stdout_text = stdout.decode(errors="replace")
        stderr_text = stderr.decode(errors="replace")

        if proc.returncode != 0:
            return ToolResult(
                success=False,
                output=stdout_text,
                error=f"Exit code {proc.returncode}: {stderr_text}",
            )
        return ToolResult.ok(stdout_text + stderr_text)
