"""Background process manager with durable metadata and bounded logs."""

from __future__ import annotations

import asyncio
import os
import shlex
import sys
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from agent33.processes.models import ManagedProcessRecord, ManagedProcessStatus
from agent33.security.redaction import redact_secrets

if TYPE_CHECKING:
    from agent33.services.orchestration_state import OrchestrationStateStore


class ProcessManagerError(Exception):
    """Base error for process manager failures."""


class ManagedProcessNotFoundError(ProcessManagerError):
    """Raised when a process does not exist or is not visible."""


class ProcessValidationError(ProcessManagerError):
    """Raised when process input fails validation."""


class ProcessLimitError(ProcessManagerError):
    """Raised when the active-process limit is exceeded."""


@dataclass(slots=True)
class _RuntimeProcessHandle:
    """Live runtime handles for a managed process."""

    process: asyncio.subprocess.Process
    stdout_task: asyncio.Task[None]
    stderr_task: asyncio.Task[None]
    wait_task: asyncio.Task[None]


def _new_process_id() -> str:
    return f"PROC-{uuid.uuid4().hex[:12]}"


def _redact_process_text(value: str) -> str:
    """Apply Phase 52 secret redaction to process-visible text."""
    return redact_secrets(value, enabled=True)


def _sanitize_process_record(record: ManagedProcessRecord) -> ManagedProcessRecord:
    """Return a copy safe for persistence and operator-facing reads."""
    return record.model_copy(
        update={
            "command": _redact_process_text(record.command),
            "last_error": _redact_process_text(record.last_error),
        }
    )


class ProcessManagerService:
    """Manage long-running subprocesses with tenant filtering and persistence."""

    _NAMESPACE = "managed_processes"

    def __init__(
        self,
        *,
        workspace_root: Path,
        log_dir: Path,
        state_store: OrchestrationStateStore | None = None,
        max_processes: int = 10,
        max_log_bytes: int = 262_144,
    ) -> None:
        self._workspace_root = workspace_root.resolve()
        self._log_dir = log_dir.resolve()
        self._state_store = state_store
        self._max_processes = max(1, max_processes)
        self._max_log_bytes = max(4096, max_log_bytes)
        self._records: dict[str, ManagedProcessRecord] = {}
        self._handles: dict[str, _RuntimeProcessHandle] = {}
        self._log_locks: dict[str, asyncio.Lock] = {}
        self._load_state()
        self._recover_interrupted()

    async def start(
        self,
        command: str,
        *,
        working_dir: str = "",
        environment: dict[str, Any] | None = None,
        agent_id: str = "",
        session_id: str = "",
        tenant_id: str = "",
        requested_by: str = "",
    ) -> ManagedProcessRecord:
        """Start a managed subprocess."""
        normalized_command = command.strip()
        if not normalized_command:
            raise ProcessValidationError("Command must not be empty")
        if len(self._handles) >= self._max_processes:
            raise ProcessLimitError(
                f"Managed process limit reached ({self._max_processes} active processes)"
            )

        resolved_working_dir = self._resolve_working_dir(working_dir)
        env = {**os.environ}
        for key, value in (environment or {}).items():
            if isinstance(key, str) and isinstance(value, (str, int, float, bool)):
                env[key] = str(value)

        process_id = _new_process_id()
        log_path = self._log_path(process_id)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("", encoding="utf-8")
        self._log_locks[process_id] = asyncio.Lock()

        try:
            if sys.platform == "win32":
                proc = await asyncio.create_subprocess_shell(
                    normalized_command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(resolved_working_dir),
                    env=env,
                )
            else:
                parts = shlex.split(normalized_command)
                if not parts:
                    raise ProcessValidationError("Command did not resolve to an executable")
                proc = await asyncio.create_subprocess_exec(
                    *parts,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(resolved_working_dir),
                    env=env,
                )
        except ValueError as exc:
            raise ProcessValidationError(f"Invalid command syntax: {exc}") from exc
        except FileNotFoundError as exc:
            redacted_command = _redact_process_text(normalized_command)
            raise ProcessValidationError(f"Command not found: {redacted_command}") from exc
        except OSError as exc:
            message = _redact_process_text(f"Failed to start command: {exc}")
            raise ProcessValidationError(message) from exc

        record = ManagedProcessRecord(
            process_id=process_id,
            command=_redact_process_text(normalized_command),
            status=ManagedProcessStatus.RUNNING,
            pid=proc.pid,
            agent_id=agent_id,
            session_id=session_id,
            tenant_id=tenant_id,
            requested_by=requested_by,
            working_dir=str(resolved_working_dir),
            log_path=str(log_path),
        )
        self._records[process_id] = record

        stdout_task = asyncio.create_task(self._consume_stream(process_id, proc.stdout, ""))
        stderr_task = asyncio.create_task(
            self._consume_stream(process_id, proc.stderr, "[stderr] ")
        )
        wait_task = asyncio.create_task(self._wait_for_process(process_id))
        self._handles[process_id] = _RuntimeProcessHandle(
            process=proc,
            stdout_task=stdout_task,
            stderr_task=stderr_task,
            wait_task=wait_task,
        )
        self._persist_state()
        return record.model_copy(deep=True)

    def list_processes(
        self,
        *,
        tenant_id: str = "",
        session_id: str = "",
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ManagedProcessRecord]:
        """Return visible processes in newest-first order."""
        records = list(self._records.values())
        if tenant_id:
            records = [record for record in records if record.tenant_id == tenant_id]
        if session_id:
            records = [record for record in records if record.session_id == session_id]
        if status:
            records = [record for record in records if record.status.value == status]
        records.sort(key=lambda item: item.started_at, reverse=True)
        start = max(0, offset)
        end = start + max(1, limit)
        return [_sanitize_process_record(record) for record in records[start:end]]

    def count_processes(
        self,
        *,
        tenant_id: str = "",
        session_id: str = "",
        status: str | None = None,
    ) -> int:
        """Return the total visible process count."""
        return len(
            self.list_processes(
                tenant_id=tenant_id,
                session_id=session_id,
                status=status,
                limit=max(len(self._records), 1),
                offset=0,
            )
        )

    def get_process(self, process_id: str, *, tenant_id: str = "") -> ManagedProcessRecord:
        """Return a single visible process."""
        record = self._records.get(process_id)
        if record is None:
            raise ManagedProcessNotFoundError(process_id)
        if tenant_id and record.tenant_id != tenant_id:
            raise ManagedProcessNotFoundError(process_id)
        return _sanitize_process_record(record)

    def read_log(self, process_id: str, *, tenant_id: str = "", tail: int = 200) -> str:
        """Return the last *tail* log lines for a visible process."""
        record = self.get_process(process_id, tenant_id=tenant_id)
        log_path = Path(record.log_path)
        if not log_path.exists():
            return ""
        content = _redact_process_text(log_path.read_text(encoding="utf-8", errors="replace"))
        lines = content.splitlines()
        capped_tail = max(1, min(tail, 2000))
        return "\n".join(lines[-capped_tail:])

    async def write_stdin(
        self,
        process_id: str,
        data: str,
        *,
        tenant_id: str = "",
    ) -> ManagedProcessRecord:
        """Write to a running process stdin."""
        record = self._records.get(process_id)
        if record is None or (tenant_id and record.tenant_id != tenant_id):
            raise ManagedProcessNotFoundError(process_id)
        if record.status != ManagedProcessStatus.RUNNING:
            raise ProcessValidationError(
                "Process is not accepting stdin because it is not running"
            )
        handle = self._handles.get(process_id)
        if handle is None or handle.process.stdin is None:
            raise ProcessValidationError("Process stdin is not available")
        handle.process.stdin.write(data.encode("utf-8"))
        await handle.process.stdin.drain()
        return record.model_copy(deep=True)

    async def terminate(
        self,
        process_id: str,
        *,
        tenant_id: str = "",
        grace_seconds: float = 3.0,
    ) -> ManagedProcessRecord:
        """Terminate a running process and return the updated record."""
        record = self._records.get(process_id)
        if record is None or (tenant_id and record.tenant_id != tenant_id):
            raise ManagedProcessNotFoundError(process_id)
        handle = self._handles.get(process_id)
        if handle is None:
            if record.status == ManagedProcessStatus.RUNNING:
                record.status = ManagedProcessStatus.INTERRUPTED
                record.finished_at = datetime.now(UTC)
                if not record.last_error:
                    record.last_error = "Runtime handle unavailable"
                self._persist_state()
            return record.model_copy(deep=True)

        record.status = ManagedProcessStatus.TERMINATED
        record.finished_at = datetime.now(UTC)
        self._persist_state()

        with suppress(ProcessLookupError):
            handle.process.terminate()
        try:
            await asyncio.wait_for(handle.wait_task, timeout=max(0.1, grace_seconds))
        except TimeoutError:
            with suppress(ProcessLookupError):
                handle.process.kill()
            await handle.wait_task
        return self.get_process(process_id, tenant_id=tenant_id)

    def cleanup_completed(self, *, tenant_id: str = "", max_age_seconds: int = 3600) -> int:
        """Delete completed or failed process records older than the cutoff."""
        cutoff = datetime.now(UTC) - timedelta(seconds=max(0, max_age_seconds))
        removed = 0
        for process_id, record in list(self._records.items()):
            if process_id in self._handles:
                continue
            if tenant_id and record.tenant_id != tenant_id:
                continue
            if record.status == ManagedProcessStatus.RUNNING:
                continue
            finished_at = record.finished_at or record.started_at
            if max_age_seconds > 0 and finished_at > cutoff:
                continue
            self._records.pop(process_id, None)
            self._log_locks.pop(process_id, None)
            with suppress(OSError):
                self._log_path(process_id).unlink(missing_ok=True)
            removed += 1
        if removed:
            self._persist_state()
        return removed

    def inventory(self) -> dict[str, int]:
        """Return lightweight inventory counts for operator status views."""
        return {"count": len(self._records), "active": len(self._handles)}

    @property
    def workspace_root(self) -> Path:
        """Return the enforced workspace root."""
        return self._workspace_root

    async def shutdown(self) -> None:
        """Terminate active processes and flush final metadata."""
        for process_id in list(self._handles):
            with suppress(ProcessManagerError):
                await self.terminate(process_id, grace_seconds=1.0)
        for handle in list(self._handles.values()):
            with suppress(Exception):
                await handle.wait_task

    async def _consume_stream(
        self,
        process_id: str,
        stream: asyncio.StreamReader | None,
        prefix: str,
    ) -> None:
        if stream is None:
            return
        while True:
            chunk = await stream.readline()
            if not chunk:
                return
            text = chunk.decode("utf-8", errors="replace")
            if prefix:
                text = "".join(f"{prefix}{line}" for line in text.splitlines(keepends=True))
            await self._append_log(process_id, text)

    async def _wait_for_process(self, process_id: str) -> None:
        handle = self._handles.get(process_id)
        if handle is None:
            return
        exit_code = await handle.process.wait()
        with suppress(Exception):
            await handle.stdout_task
        with suppress(Exception):
            await handle.stderr_task

        record = self._records.get(process_id)
        if record is not None:
            record.exit_code = exit_code
            record.finished_at = datetime.now(UTC)
            if record.status != ManagedProcessStatus.TERMINATED:
                if exit_code == 0:
                    record.status = ManagedProcessStatus.COMPLETED
                else:
                    record.status = ManagedProcessStatus.FAILED
                    if not record.last_error:
                        record.last_error = f"Process exited with code {exit_code}"
                    if sys.platform == "win32":
                        log_tail = self.read_log(process_id, tail=20)
                        if "is not recognized" in log_tail and not record.last_error:
                            record.last_error = "Command not found"
            self._persist_state()
        self._handles.pop(process_id, None)

    async def _append_log(self, process_id: str, text: str) -> None:
        if not text:
            return
        lock = self._log_locks.setdefault(process_id, asyncio.Lock())
        async with lock:
            log_path = self._log_path(process_id)
            safe_text = _redact_process_text(text)
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(safe_text)
            self._truncate_log_if_needed(log_path)

    def _truncate_log_if_needed(self, log_path: Path) -> None:
        try:
            if log_path.stat().st_size <= self._max_log_bytes:
                return
            with log_path.open("rb") as handle:
                handle.seek(-self._max_log_bytes, os.SEEK_END)
                data = handle.read()
            with log_path.open("wb") as handle:
                handle.write(data)
        except OSError:
            return

    def _resolve_working_dir(self, working_dir: str) -> Path:
        raw = working_dir.strip()
        candidate = self._workspace_root if not raw else Path(raw)
        resolved = (
            candidate.resolve()
            if candidate.is_absolute()
            else (self._workspace_root / candidate).resolve()
        )
        if not self._is_within_workspace(resolved):
            raise ProcessValidationError(
                f"Working directory '{resolved}' escapes workspace root '{self._workspace_root}'"
            )
        if not resolved.exists() or not resolved.is_dir():
            raise ProcessValidationError(f"Working directory does not exist: {resolved}")
        return resolved

    def _is_within_workspace(self, path: Path) -> bool:
        try:
            path.relative_to(self._workspace_root)
            return True
        except ValueError:
            return False

    def _log_path(self, process_id: str) -> Path:
        return self._log_dir / f"{process_id}.log"

    def _persist_state(self) -> None:
        if self._state_store is None:
            return
        self._state_store.write_namespace(
            self._NAMESPACE,
            {
                "records": [
                    _sanitize_process_record(record).model_dump(mode="json")
                    for record in self._records.values()
                ]
            },
        )

    def _load_state(self) -> None:
        if self._state_store is None:
            return
        payload = self._state_store.read_namespace(self._NAMESPACE)
        records_payload = payload.get("records", [])
        if not isinstance(records_payload, list):
            return
        loaded: dict[str, ManagedProcessRecord] = {}
        changed = False
        for item in records_payload:
            try:
                record = ManagedProcessRecord.model_validate(item)
            except ValidationError:
                continue
            sanitized = _sanitize_process_record(record)
            if sanitized.command != record.command or sanitized.last_error != record.last_error:
                changed = True
            loaded[record.process_id] = sanitized
        self._records = loaded
        if changed:
            self._persist_state()

    def _recover_interrupted(self) -> None:
        changed = False
        for record in self._records.values():
            if record.status != ManagedProcessStatus.RUNNING:
                continue
            record.status = ManagedProcessStatus.INTERRUPTED
            record.finished_at = datetime.now(UTC)
            if not record.last_error:
                record.last_error = "Recovered after restart without a live process handle"
            changed = True
        if changed:
            self._persist_state()
