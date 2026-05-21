"""Tests for the managed process service."""

from __future__ import annotations

import asyncio
import shlex
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest

import agent33.processes.service as process_service_module
from agent33.processes.models import ManagedProcessStatus
from agent33.processes.service import (
    ManagedProcessNotFoundError,
    ProcessManagerService,
    ProcessValidationError,
)
from agent33.services.orchestration_state import OrchestrationStateStore

if TYPE_CHECKING:
    from pathlib import Path


def _python_command(code: str) -> str:
    parts = [sys.executable, "-u", "-c", code]
    if sys.platform == "win32":
        return subprocess.list2cmdline(parts)
    return shlex.join(parts)


async def _wait_for_terminal(
    service: ProcessManagerService,
    process_id: str,
    *,
    timeout_seconds: float = 5.0,
) -> tuple[ManagedProcessStatus, str]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        record = service.get_process(process_id)
        if record.status != ManagedProcessStatus.RUNNING:
            return record.status, service.read_log(process_id, tail=50)
        await asyncio.sleep(0.05)
    raise AssertionError(f"Process {process_id} did not finish within {timeout_seconds}s")


@pytest.mark.asyncio()
async def test_process_lifecycle_and_log_tail(tmp_path: Path) -> None:
    service = ProcessManagerService(
        workspace_root=tmp_path,
        log_dir=tmp_path / "logs",
        max_processes=4,
    )
    try:
        record = await service.start(_python_command('print("alpha", flush=True)'))
        status, log_tail = await _wait_for_terminal(service, record.process_id)
        assert status == ManagedProcessStatus.COMPLETED
        stored = service.get_process(record.process_id)
        assert stored.exit_code == 0
        assert "alpha" in log_tail
        listing = service.list_processes()
        assert len(listing) == 1
        assert listing[0].process_id == record.process_id
    finally:
        await service.shutdown()


@pytest.mark.asyncio()
async def test_process_command_log_and_state_are_redacted(tmp_path: Path) -> None:
    state_store = OrchestrationStateStore(str(tmp_path / "state.json"))
    service = ProcessManagerService(
        workspace_root=tmp_path,
        log_dir=tmp_path / "logs",
        state_store=state_store,
        max_processes=4,
    )
    secret = "sk-ant-" + "a" * 30
    try:
        record = await service.start(_python_command(f'print("token={secret}", flush=True)'))
        status, log_tail = await _wait_for_terminal(service, record.process_id)
        assert status == ManagedProcessStatus.COMPLETED
        assert secret not in record.command
        stored = service.get_process(record.process_id)
        assert secret not in stored.command
        assert secret not in log_tail

        payload = state_store.read_namespace("managed_processes")
        persisted = payload["records"][0]
        assert secret not in persisted["command"]
    finally:
        await service.shutdown()


@pytest.mark.asyncio()
async def test_command_not_found_error_uses_redacted_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = ProcessManagerService(
        workspace_root=tmp_path,
        log_dir=tmp_path / "logs",
        max_processes=4,
    )

    async def _boom(*args: object, **kwargs: object) -> object:
        raise FileNotFoundError("missing")

    if sys.platform == "win32":
        monkeypatch.setattr(process_service_module.asyncio, "create_subprocess_shell", _boom)
    else:
        monkeypatch.setattr(process_service_module.asyncio, "create_subprocess_exec", _boom)

    command = "runner --password=example-placeholder-value-12345"
    with pytest.raises(ProcessValidationError, match="Command not found: ") as excinfo:
        await service.start(command)

    message = str(excinfo.value)
    assert "example-placeholder-value-12345" not in message
    assert "runner --password=" in message
    assert "..." in message or "***" in message


@pytest.mark.asyncio()
async def test_process_write_stdin_and_cleanup(tmp_path: Path) -> None:
    service = ProcessManagerService(
        workspace_root=tmp_path,
        log_dir=tmp_path / "logs",
        max_processes=4,
    )
    try:
        record = await service.start(
            _python_command(
                "import sys; data = sys.stdin.readline().strip(); "
                'print(f"echo:{data}", flush=True)'
            )
        )
        await service.write_stdin(record.process_id, "hello from test\n")
        status, log_tail = await _wait_for_terminal(service, record.process_id)
        assert status == ManagedProcessStatus.COMPLETED
        assert "echo:hello from test" in log_tail
        removed = service.cleanup_completed(max_age_seconds=0)
        assert removed == 1
        with pytest.raises(ManagedProcessNotFoundError):
            service.get_process(record.process_id)
    finally:
        await service.shutdown()


@pytest.mark.asyncio()
async def test_process_terminate_and_escape_rejection(tmp_path: Path) -> None:
    service = ProcessManagerService(
        workspace_root=tmp_path,
        log_dir=tmp_path / "logs",
        max_processes=4,
    )
    outside_dir = tmp_path.parent
    try:
        with pytest.raises(ProcessValidationError):
            await service.start(
                _python_command('print("nope", flush=True)'),
                working_dir=str(outside_dir),
            )

        record = await service.start(_python_command("import time; time.sleep(10)"))
        terminated = await service.terminate(record.process_id)
        assert terminated.status == ManagedProcessStatus.TERMINATED
    finally:
        await service.shutdown()


def test_running_records_recover_as_interrupted(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_store = OrchestrationStateStore(str(state_path))
    state_store.write_namespace(
        "managed_processes",
        {
            "records": [
                {
                    "process_id": "PROC-stale",
                    "command": "python -u -c print('stale')",
                    "status": "running",
                    "started_at": "2026-03-12T00:00:00+00:00",
                    "tenant_id": "tenant-a",
                    "working_dir": str(tmp_path),
                    "log_path": str(tmp_path / "logs" / "PROC-stale.log"),
                }
            ]
        },
    )

    service = ProcessManagerService(
        workspace_root=tmp_path,
        log_dir=tmp_path / "logs",
        state_store=state_store,
    )

    record = service.get_process("PROC-stale", tenant_id="tenant-a")
    assert record.status == ManagedProcessStatus.INTERRUPTED
    assert "Recovered after restart" in record.last_error
