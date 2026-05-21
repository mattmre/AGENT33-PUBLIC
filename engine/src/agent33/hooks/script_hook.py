"""ScriptHook adapter: wraps file-based hook scripts into the Hook protocol."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING, Any, Literal

from agent33.hooks.protocol import BaseHook

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from agent33.hooks.models import HookContext

logger = logging.getLogger(__name__)


class ScriptHook(BaseHook):
    """Adapts a file-based hook script into the Hook protocol.

    Executes the script as a subprocess, passing context as JSON on stdin
    and reading modified context from stdout. Enforces per-hook timeout.
    Fail-open by default: if the script crashes, returns exit code != 0,
    or times out, the chain continues.
    """

    def __init__(
        self,
        *,
        name: str,
        event_type: str,
        script_path: Path,
        timeout_ms: float = 5000.0,
        fail_mode: Literal["open", "closed"] = "open",
        priority: int = 200,
        tenant_id: str = "",
    ) -> None:
        super().__init__(
            name=name,
            event_type=event_type,
            priority=priority,
            enabled=True,
            tenant_id=tenant_id,
        )
        self._script_path = script_path
        self._timeout_ms = timeout_ms
        self._fail_mode = fail_mode
        self._execution_log: list[dict[str, Any]] = []

    @property
    def script_path(self) -> Path:
        return self._script_path

    @property
    def fail_mode(self) -> str:
        return self._fail_mode

    @property
    def execution_log(self) -> list[dict[str, Any]]:
        """Recent execution log entries for diagnostics."""
        return list(self._execution_log[-50:])

    async def execute(
        self,
        context: HookContext,
        call_next: Callable[[HookContext], Awaitable[HookContext]],
    ) -> HookContext:
        """Run the script subprocess, enforce timeout, parse output."""
        if not self._script_path.exists():
            logger.warning(
                "script_hook_missing path=%s name=%s",
                self._script_path,
                self._name,
            )
            return await call_next(context)

        # Build environment for subprocess
        env = dict(os.environ)
        env["AGENT33_EVENT_TYPE"] = context.event_type
        env["AGENT33_TENANT_ID"] = context.tenant_id
        session_id = context.metadata.get("session_id", "")
        if session_id:
            env["AGENT33_SESSION_ID"] = str(session_id)
        session_base_dir = context.metadata.get("session_base_dir", "")
        if session_base_dir:
            env["AGENT33_SESSION_BASE_DIR"] = str(session_base_dir)

        # Serialize context to JSON for stdin
        stdin_data = json.dumps(
            {
                "event_type": context.event_type,
                "tenant_id": context.tenant_id,
                "metadata": context.metadata,
            }
        )

        log_entry: dict[str, Any] = {
            "hook_name": self._name,
            "script_path": str(self._script_path),
            "event_type": context.event_type,
        }

        try:
            cmd = _build_command(self._script_path)
            result = await asyncio.wait_for(
                _run_subprocess(cmd, stdin_data, env),
                timeout=self._timeout_ms / 1000.0,
            )
            stdout, stderr, returncode = result

            log_entry["returncode"] = returncode
            log_entry["stderr"] = stderr or ""
            if stderr:
                logger.debug(
                    "script_hook_stderr name=%s stderr=%s",
                    self._name,
                    stderr,
                )

            if returncode != 0:
                logger.warning(
                    "script_hook_failed name=%s exit=%d stderr=%s",
                    self._name,
                    returncode,
                    _stderr_excerpt(stderr, limit=200),
                )
                log_entry["success"] = False
                self._execution_log.append(log_entry)
                if self._fail_mode == "closed":
                    context.abort = True
                    context.abort_reason = (
                        f"Script hook '{self._name}' exited with code {returncode}"
                    )
                    return context
                return await call_next(context)

            # Parse stdout for context modifications
            if stdout and stdout.strip():
                try:
                    output = json.loads(stdout)
                    if isinstance(output, dict):
                        if output.get("abort"):
                            context.abort = True
                            context.abort_reason = output.get(
                                "abort_reason",
                                f"Script hook '{self._name}' requested abort",
                            )
                            log_entry["abort"] = True
                            self._execution_log.append(log_entry)
                            return context
                        if "metadata" in output and isinstance(output["metadata"], dict):
                            context.metadata.update(output["metadata"])
                except json.JSONDecodeError:
                    logger.debug(
                        "script_hook_stdout_not_json name=%s",
                        self._name,
                    )

            log_entry["success"] = True
            self._execution_log.append(log_entry)
            return await call_next(context)

        except TimeoutError:
            logger.warning(
                "script_hook_timeout name=%s timeout_ms=%s",
                self._name,
                self._timeout_ms,
            )
            log_entry["success"] = False
            log_entry["error"] = "timeout"
            self._execution_log.append(log_entry)
            if self._fail_mode == "closed":
                context.abort = True
                context.abort_reason = (
                    f"Script hook '{self._name}' timed out after {self._timeout_ms}ms"
                )
                return context
            return await call_next(context)
        except Exception as exc:
            logger.warning(
                "script_hook_error name=%s error=%s",
                self._name,
                exc,
            )
            log_entry["success"] = False
            log_entry["error"] = str(exc)
            self._execution_log.append(log_entry)
            if self._fail_mode == "closed":
                context.abort = True
                context.abort_reason = f"Script hook '{self._name}' failed: {exc}"
                return context
            return await call_next(context)


def _build_command(script_path: Path) -> list[str]:
    """Build the subprocess command based on script extension."""
    suffix = script_path.suffix.lower()
    if suffix == ".py":
        return [sys.executable, str(script_path)]
    elif suffix == ".js":
        return ["node", str(script_path)]
    elif suffix == ".sh":
        if sys.platform == "win32":
            bash = shutil.which("bash")
            if bash is None:
                raise FileNotFoundError("bash is required to execute .sh hook scripts on Windows")
            return [bash, str(script_path)]
        return [str(script_path)]
    elif suffix == ".ps1":
        return ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script_path)]
    else:
        raise ValueError(f"Unsupported script extension: {suffix or '<none>'}")


async def _run_subprocess(
    cmd: list[str],
    stdin_data: str,
    env: dict[str, str],
) -> tuple[str, str, int]:
    """Run a subprocess asynchronously, returning (stdout, stderr, returncode)."""
    if sys.platform == "win32":
        # On Windows, use subprocess.list2cmdline for proper quoting
        cmd_str = subprocess.list2cmdline(cmd)
        proc = await asyncio.create_subprocess_shell(
            cmd_str,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    else:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

    stdout_bytes, stderr_bytes = await proc.communicate(stdin_data.encode())
    stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
    stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
    returncode = proc.returncode or 0
    return stdout, stderr, returncode


def _stderr_excerpt(stderr: str, *, limit: int) -> str:
    """Return a concise stderr preview for warning-level logs."""
    if len(stderr) <= limit:
        return stderr
    return f"{stderr[:limit]}..."
