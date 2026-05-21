"""CLI adapter — translates an ExecutionContract into a subprocess invocation."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time

import structlog

from agent33.execution.adapters.base import BaseAdapter
from agent33.execution.models import (
    AdapterDefinition,
    ExecutionContract,
    ExecutionResult,
)

logger = structlog.get_logger()

# Output capture limits (bytes).
_STDOUT_LIMIT = 1_048_576  # 1 MB
_STDERR_LIMIT = 262_144  # 256 KB


class CLIAdapter(BaseAdapter):
    """Execute a contract by spawning a subprocess.

    Builds the command from the adapter's :class:`CLIInterface` definition
    (executable + base_args + arg_mapping + raw arguments), passes
    environment variables from the contract, enforces the sandbox timeout,
    and captures stdout/stderr with truncation.
    """

    def __init__(self, definition: AdapterDefinition) -> None:
        super().__init__(definition)
        if definition.cli is None:
            raise ValueError(
                f"CLIAdapter requires a 'cli' interface on adapter '{definition.adapter_id}'"
            )

    async def execute(self, contract: ExecutionContract) -> ExecutionResult:
        """Spawn a subprocess and return the captured result."""
        start = time.monotonic()
        cli = self._definition.cli
        assert cli is not None  # guaranteed by __init__

        # -- Build command parts -----------------------------------------------
        parts: list[str] = [cli.executable, *cli.base_args]

        # Apply arg_mapping: substitute {value} with the actual argument value.
        for key, template in cli.arg_mapping.items():
            value = contract.inputs.environment.get(key, "")
            if value:
                parts.append(template.replace("{value}", value))

        # Append raw arguments from the contract.
        parts.extend(contract.inputs.arguments)

        # -- Environment -------------------------------------------------------
        # Merge contract environment on top of the current OS environment so
        # that PATH and other essentials are preserved.
        env: dict[str, str] | None = None
        if contract.inputs.environment:
            env = {**os.environ, **contract.inputs.environment}

        # -- Timeout from sandbox config (ms → seconds) -----------------------
        timeout_s = contract.sandbox.timeout_ms / 1000.0

        # -- Spawn process (platform-aware) ------------------------------------
        try:
            if sys.platform == "win32":
                cmd_str = subprocess.list2cmdline(parts)
                proc = await asyncio.create_subprocess_shell(
                    cmd_str,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                    cwd=contract.inputs.working_directory,
                )
            else:
                proc = await asyncio.create_subprocess_exec(
                    *parts,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                    cwd=contract.inputs.working_directory,
                )
        except FileNotFoundError:
            elapsed = (time.monotonic() - start) * 1000
            return ExecutionResult(
                execution_id=contract.execution_id,
                success=False,
                exit_code=127,
                error=f"Command not found: {cli.executable}",
                duration_ms=round(elapsed, 2),
            )
        except PermissionError:
            elapsed = (time.monotonic() - start) * 1000
            return ExecutionResult(
                execution_id=contract.execution_id,
                success=False,
                exit_code=126,
                error=f"Permission denied: {cli.executable}",
                duration_ms=round(elapsed, 2),
            )

        # -- Communicate with timeout ------------------------------------------
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_s,
            )
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            elapsed = (time.monotonic() - start) * 1000
            logger.warning(
                "cli_adapter_timeout",
                adapter_id=self.adapter_id,
                timeout_s=timeout_s,
            )
            return ExecutionResult(
                execution_id=contract.execution_id,
                success=False,
                exit_code=143,
                error=f"Execution timed out after {timeout_s}s",
                duration_ms=round(elapsed, 2),
            )

        # -- Capture and truncate output ---------------------------------------
        truncated = False

        if len(stdout_bytes) > _STDOUT_LIMIT:
            stdout_bytes = stdout_bytes[:_STDOUT_LIMIT]
            truncated = True
        if len(stderr_bytes) > _STDERR_LIMIT:
            stderr_bytes = stderr_bytes[:_STDERR_LIMIT]
            truncated = True

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        exit_code = proc.returncode if proc.returncode is not None else -1

        # On Windows, cmd.exe doesn't raise FileNotFoundError — detect via
        # stderr message and normalise to exit code 127 per spec.
        if sys.platform == "win32" and exit_code != 0 and "is not recognized" in stderr:
            exit_code = 127

        elapsed = (time.monotonic() - start) * 1000

        logger.info(
            "cli_adapter_complete",
            adapter_id=self.adapter_id,
            exit_code=exit_code,
            stdout_len=len(stdout),
            duration_ms=round(elapsed, 2),
        )

        return ExecutionResult(
            execution_id=contract.execution_id,
            success=exit_code == 0,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=round(elapsed, 2),
            truncated=truncated,
        )
