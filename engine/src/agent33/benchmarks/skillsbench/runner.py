"""Binary reward evaluator using subprocess pytest.

SkillsBench uses pytest as the verification harness: all tests in a task's
``tests/test_outputs.py`` must pass for the trial to be counted as a pass.
This module runs that file in a subprocess so the evaluation is isolated
from the AGENT-33 process.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PytestResult:
    """Result of a single subprocess pytest run."""

    passed: bool
    """True if all tests passed (returncode == 0)."""

    returncode: int
    """Raw subprocess return code."""

    stdout: str
    """Captured standard output."""

    stderr: str
    """Captured standard error."""

    duration_ms: float
    """Wall-clock time in milliseconds."""


class PytestBinaryRewardRunner:
    """Run a SkillsBench task's pytest to determine binary pass/fail.

    Parameters
    ----------
    timeout_seconds:
        Maximum time to wait for the pytest subprocess to complete.
        Defaults to 300 s (5 minutes) to match SkillsBench conventions.
    python_executable:
        Path to the Python interpreter to use for running pytest.
        Defaults to ``sys.executable``.
    """

    def __init__(
        self,
        timeout_seconds: float = 300.0,
        python_executable: str | None = None,
    ) -> None:
        self._timeout = timeout_seconds
        self._python_executable = python_executable or sys.executable

    @property
    def timeout_seconds(self) -> float:
        """Return the configured timeout."""
        return self._timeout

    async def evaluate(
        self,
        tests_path: Path,
        working_dir: Path,
    ) -> PytestResult:
        """Run pytest on the task's test file against agent outputs.

        Parameters
        ----------
        tests_path:
            Absolute path to the pytest file (``tests/test_outputs.py``).
        working_dir:
            Working directory for the subprocess; agent outputs should be
            written here before calling this method.

        Returns
        -------
        PytestResult
            ``passed=True`` iff pytest exited with return code 0.
        """
        if not tests_path.is_file():
            logger.warning("pytest test file not found: %s", tests_path)
            return PytestResult(
                passed=False,
                returncode=-1,
                stdout="",
                stderr=f"Test file not found: {tests_path}",
                duration_ms=0.0,
            )

        cmd = [
            self._python_executable,
            "-m",
            "pytest",
            str(tests_path),
            "-v",
            "--tb=short",
        ]

        # Preserve the current PATH so pytest can find installed packages
        env = {**os.environ}

        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(working_dir),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                raw_stdout, raw_stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self._timeout,
                )
            except TimeoutError:
                proc.kill()
                await proc.communicate()
                duration_ms = (time.monotonic() - start) * 1000.0
                logger.warning(
                    "pytest_timeout tests=%s timeout=%.1fs",
                    tests_path,
                    self._timeout,
                )
                return PytestResult(
                    passed=False,
                    returncode=-1,
                    stdout="",
                    stderr=f"Timed out after {self._timeout}s",
                    duration_ms=duration_ms,
                )

            duration_ms = (time.monotonic() - start) * 1000.0
            returncode = proc.returncode if proc.returncode is not None else -1
            stdout = raw_stdout.decode("utf-8", errors="replace")
            stderr = raw_stderr.decode("utf-8", errors="replace")

            logger.debug(
                "pytest_complete tests=%s returncode=%d duration_ms=%.0f",
                tests_path,
                returncode,
                duration_ms,
            )
            return PytestResult(
                passed=(returncode == 0),
                returncode=returncode,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration_ms,
            )

        except Exception as exc:
            duration_ms = (time.monotonic() - start) * 1000.0
            logger.warning(
                "pytest_runner_error tests=%s error=%s",
                tests_path,
                exc,
                exc_info=True,
            )
            return PytestResult(
                passed=False,
                returncode=-1,
                stdout="",
                stderr=str(exc),
                duration_ms=duration_ms,
            )
