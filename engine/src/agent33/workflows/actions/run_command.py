"""Action that runs a shell command via asyncio subprocess."""

from __future__ import annotations

import asyncio
import shlex
import sys
from typing import Any

import structlog

logger = structlog.get_logger()


async def execute(
    command: str | None,
    inputs: dict[str, Any],
    timeout_seconds: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run a shell command and capture its output.

    Environment variables from inputs are passed to the subprocess. The
    command string is split using shlex on non-Windows platforms.

    Args:
        command: The command string to execute.
        inputs: Additional environment variables passed to the subprocess.
        timeout_seconds: Maximum seconds to allow the process to run.
        dry_run: If True, log the command without executing.

    Returns:
        A dict with stdout, stderr, and return_code.

    Raises:
        ValueError: If command is not provided.
        TimeoutError: If the process exceeds timeout_seconds.
        RuntimeError: If the process exits with a non-zero code.
    """
    if not command:
        raise ValueError("run-command action requires a 'command' field")

    logger.info("run_command", command=command, dry_run=dry_run)

    if dry_run:
        return {"dry_run": True, "command": command}

    # Build environment variables: merge inputs into the current process env
    # so that PATH and other system variables are preserved (critical on Windows).
    import os

    env_vars: dict[str, str] = {**os.environ}
    for k, v in inputs.items():
        if isinstance(v, (str, int, float, bool)):
            env_vars[k] = str(v)

    if sys.platform == "win32":
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env_vars,
        )
    else:
        args = shlex.split(command)
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env_vars,
        )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=float(timeout_seconds) if timeout_seconds else None,
        )
    except TimeoutError as exc:
        proc.kill()
        await proc.communicate()
        raise TimeoutError(f"Command timed out after {timeout_seconds}s: {command}") from exc

    stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
    stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
    return_code = proc.returncode or 0

    logger.info(
        "run_command_complete",
        command=command,
        return_code=return_code,
        stdout_len=len(stdout),
    )

    if return_code != 0:
        raise RuntimeError(f"Command failed with code {return_code}: {stderr or stdout}")

    return {"stdout": stdout, "stderr": stderr, "return_code": return_code}
