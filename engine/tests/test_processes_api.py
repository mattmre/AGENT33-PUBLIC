"""API tests for managed background processes."""

from __future__ import annotations

import asyncio
import contextlib
import shlex
import subprocess
import sys
import time
from typing import TYPE_CHECKING, Any

import httpx
import pytest
import pytest_asyncio

from agent33.main import app
from agent33.processes.service import ProcessManagerService
from agent33.security.auth import create_access_token
from agent33.tools.governance import ToolGovernance

if TYPE_CHECKING:
    from pathlib import Path


def _python_command(code: str) -> str:
    parts = [sys.executable, "-u", "-c", code]
    if sys.platform == "win32":
        return subprocess.list2cmdline(parts)
    return shlex.join(parts)


def _auth_headers(*, scopes: list[str] | None = None) -> dict[str, str]:
    token = create_access_token(
        "process-user",
        scopes=scopes or [],
        tenant_id="tenant-a",
    )
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(autouse=True)
async def _install_process_service(tmp_path: Path) -> Any:
    original = getattr(app.state, "process_manager_service", None)
    service = ProcessManagerService(
        workspace_root=tmp_path,
        log_dir=tmp_path / "logs",
        max_processes=4,
    )
    app.state.process_manager_service = service
    yield service
    await service.shutdown()
    if original is not None:
        app.state.process_manager_service = original
    else:
        with contextlib.suppress(AttributeError):
            del app.state.process_manager_service


@pytest_asyncio.fixture(autouse=True)
async def _install_tool_governance() -> Any:
    original = getattr(app.state, "tool_governance", None)
    app.state.tool_governance = ToolGovernance()
    yield app.state.tool_governance
    if original is not None:
        app.state.tool_governance = original
    else:
        with contextlib.suppress(AttributeError):
            del app.state.tool_governance


@pytest_asyncio.fixture()
async def async_client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio()
async def test_processes_auth_enforced(async_client: httpx.AsyncClient) -> None:
    no_auth_list = await async_client.get("/v1/processes")
    no_auth_start = await async_client.post("/v1/processes", json={"command": "echo hi"})
    wrong_scope_list = await async_client.get(
        "/v1/processes",
        headers=_auth_headers(scopes=["agents:read"]),
    )
    wrong_scope_start = await async_client.post(
        "/v1/processes",
        json={"command": "echo hi"},
        headers=_auth_headers(scopes=["agents:read"]),
    )

    assert no_auth_list.status_code == 401
    assert no_auth_start.status_code == 401
    assert wrong_scope_list.status_code == 403
    assert wrong_scope_start.status_code == 403


@pytest.mark.asyncio()
async def test_start_list_get_log_and_cleanup(async_client: httpx.AsyncClient) -> None:
    headers = _auth_headers(scopes=["processes:read", "processes:manage", "tools:execute"])
    secret = "sk-ant-" + "a" * 30
    start = await async_client.post(
        "/v1/processes",
        json={"command": _python_command(f'print("api-alpha {secret}", flush=True)')},
        headers=headers,
    )
    assert start.status_code == 200
    assert secret not in start.json()["command"]
    process_id = start.json()["process_id"]

    deadline = time.monotonic() + 5.0
    current = start.json()
    while time.monotonic() < deadline:
        current_resp = await async_client.get(f"/v1/processes/{process_id}", headers=headers)
        current = current_resp.json()
        if current["status"] != "running":
            break
        await asyncio.sleep(0.05)
    assert current["status"] == "completed"
    assert secret not in current["command"]

    listing = await async_client.get("/v1/processes", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["count"] >= 1
    assert all(secret not in process["command"] for process in listing.json()["processes"])

    log_resp = await async_client.get(f"/v1/processes/{process_id}/log", headers=headers)
    assert log_resp.status_code == 200
    assert "api-alpha" in log_resp.json()["content"]
    assert secret not in log_resp.json()["content"]

    cleanup = await async_client.post(
        "/v1/processes/cleanup",
        json={"max_age_seconds": 0},
        headers=headers,
    )
    assert cleanup.status_code == 200
    assert cleanup.json()["removed"] >= 1


@pytest.mark.asyncio()
async def test_start_requires_tools_execute_when_governance_active(
    async_client: httpx.AsyncClient,
) -> None:
    headers = _auth_headers(scopes=["processes:read", "processes:manage"])
    start = await async_client.post(
        "/v1/processes",
        json={"command": _python_command('print("governed", flush=True)')},
        headers=headers,
    )

    assert start.status_code == 403
    assert start.json()["detail"] == "Process start blocked by tool governance"


@pytest.mark.asyncio()
async def test_terminate_and_write_input(async_client: httpx.AsyncClient) -> None:
    headers = _auth_headers(scopes=["processes:read", "processes:manage", "tools:execute"])
    writer = await async_client.post(
        "/v1/processes",
        json={
            "command": _python_command(
                "import sys; value = sys.stdin.readline().strip(); print(value, flush=True)"
            )
        },
        headers=headers,
    )
    assert writer.status_code == 200
    process_id = writer.json()["process_id"]

    write = await async_client.post(
        f"/v1/processes/{process_id}/write",
        json={"data": "payload-from-api\n"},
        headers=headers,
    )
    assert write.status_code == 200

    deadline = time.monotonic() + 5.0
    current = writer.json()
    while time.monotonic() < deadline:
        current_resp = await async_client.get(f"/v1/processes/{process_id}", headers=headers)
        current = current_resp.json()
        if current["status"] != "running":
            break
        await asyncio.sleep(0.05)
    assert current["status"] == "completed"

    log_resp = await async_client.get(f"/v1/processes/{process_id}/log", headers=headers)
    assert "payload-from-api" in log_resp.json()["content"]

    sleeper = await async_client.post(
        "/v1/processes",
        json={"command": _python_command("import time; time.sleep(10)")},
        headers=headers,
    )
    assert sleeper.status_code == 200
    sleep_id = sleeper.json()["process_id"]
    terminated = await async_client.delete(f"/v1/processes/{sleep_id}", headers=headers)
    assert terminated.status_code == 200
    assert terminated.json()["status"] == "terminated"
