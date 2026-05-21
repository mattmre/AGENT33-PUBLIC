"""API tests for platform backup routes."""

from __future__ import annotations

import contextlib
import shutil
from pathlib import Path  # noqa: TC003
from typing import Any

import httpx
import pytest
import pytest_asyncio

from agent33.backup.service import BackupService
from agent33.config import Settings
from agent33.main import app
from agent33.security.auth import create_access_token


def _auth_headers(*, scopes: list[str] | None = None) -> dict[str, str]:
    token = create_access_token(
        "backup-user",
        scopes=scopes or [],
        tenant_id="tenant-a",
    )
    return {"Authorization": f"Bearer {token}"}


def _seed_tree(root: Path) -> None:
    (root / ".env").write_text("API_SECRET_KEY=test\n", encoding="utf-8")
    (root / "agent-definitions").mkdir(parents=True, exist_ok=True)
    (root / "agent-definitions" / "alpha.yaml").write_text("name: alpha\n", encoding="utf-8")
    (root / "workflow-definitions").mkdir(parents=True, exist_ok=True)
    (root / "workflow-definitions" / "flow.yaml").write_text("steps: []\n", encoding="utf-8")
    (root / "skills").mkdir(parents=True, exist_ok=True)
    (root / "skills" / "skill.md").write_text("# Skill\n", encoding="utf-8")
    (root / "packs").mkdir(parents=True, exist_ok=True)
    (root / "packs" / "pack.yaml").write_text("name: pack\n", encoding="utf-8")
    (root / "plugins").mkdir(parents=True, exist_ok=True)
    (root / "plugins" / "plugin.yaml").write_text("name: plugin\n", encoding="utf-8")
    (root / "hook-definitions").mkdir(parents=True, exist_ok=True)
    (root / "hook-definitions" / "hook.sh").write_text("echo hook\n", encoding="utf-8")
    (root / "var").mkdir(parents=True, exist_ok=True)
    (root / "var" / "plugin_lifecycle_state.json").write_text("{}", encoding="utf-8")
    (root / "var" / "synthetic_environment_bundles.json").write_text("[]", encoding="utf-8")
    (root / "var" / "improvement_learning_signals.json").write_text("{}", encoding="utf-8")
    (root / "var" / "process-manager").mkdir(parents=True, exist_ok=True)
    (root / "var" / "process-manager" / "proc.log").write_text("hello\n", encoding="utf-8")
    (root / "sessions").mkdir(parents=True, exist_ok=True)
    (root / "sessions" / "session.json").write_text('{"id":"s1"}', encoding="utf-8")


def _settings(root: Path) -> Settings:
    return Settings(
        agent_definitions_dir="agent-definitions",
        synthetic_env_workflow_dir="workflow-definitions",
        skill_definitions_dir="skills",
        pack_definitions_dir="packs",
        plugin_definitions_dir="plugins",
        hooks_definitions_dir="hook-definitions",
        plugin_state_store_path="var/plugin_lifecycle_state.json",
        synthetic_env_bundle_persistence_path="var/synthetic_environment_bundles.json",
        process_manager_log_dir="var/process-manager",
        improvement_learning_persistence_backend="file",
        improvement_learning_persistence_path="var/improvement_learning_signals.json",
        operator_session_base_dir=str(root / "sessions"),
        backup_dir=str(root / "backups"),
    )


@pytest_asyncio.fixture(autouse=True)
async def _install_backup_service(tmp_path: Path) -> Any:
    _seed_tree(tmp_path)
    original = getattr(app.state, "backup_service", None)
    service = BackupService(
        backup_dir=tmp_path / "backups",
        settings=_settings(tmp_path),
        app_root=tmp_path,
        workspace_dir=None,
    )
    app.state.backup_service = service
    yield service
    if original is not None:
        app.state.backup_service = original
    else:
        with contextlib.suppress(AttributeError):
            del app.state.backup_service


@pytest_asyncio.fixture()
async def async_client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio()
async def test_backup_routes_enforce_auth(async_client: httpx.AsyncClient) -> None:
    no_auth = await async_client.get("/v1/backups")
    wrong_scope = await async_client.get(
        "/v1/backups",
        headers=_auth_headers(scopes=["agents:read"]),
    )
    write_without_scope = await async_client.post(
        "/v1/backups",
        json={"mode": "full"},
        headers=_auth_headers(scopes=["operator:read"]),
    )

    assert no_auth.status_code == 401
    assert wrong_scope.status_code == 403
    assert write_without_scope.status_code == 403


@pytest.mark.asyncio()
async def test_backup_routes_create_list_detail_verify(async_client: httpx.AsyncClient) -> None:
    write_headers = _auth_headers(scopes=["operator:read", "operator:write"])
    read_headers = _auth_headers(scopes=["operator:read"])

    inventory = await async_client.get("/v1/backups/inventory", headers=read_headers)
    assert inventory.status_code == 200
    assert inventory.json()["count"] > 0

    created = await async_client.post(
        "/v1/backups",
        json={"mode": "no-workspace", "label": "api"},
        headers=write_headers,
    )
    assert created.status_code == 200
    backup_id = created.json()["backup_id"]

    listing = await async_client.get("/v1/backups", headers=read_headers)
    assert listing.status_code == 200
    assert listing.json()["count"] == 1

    detail = await async_client.get(f"/v1/backups/{backup_id}", headers=read_headers)
    assert detail.status_code == 200
    assert detail.json()["manifest"]["backup_id"] == backup_id

    verify = await async_client.post(f"/v1/backups/{backup_id}/verify", headers=read_headers)
    assert verify.status_code == 200
    assert verify.json()["valid"] is True


@pytest.mark.asyncio()
async def test_backup_routes_restore_plan(async_client: httpx.AsyncClient) -> None:
    write_headers = _auth_headers(scopes=["operator:read", "operator:write"])
    read_headers = _auth_headers(scopes=["operator:read"])

    created = await async_client.post(
        "/v1/backups",
        json={"mode": "no-workspace", "label": "restore-api"},
        headers=write_headers,
    )
    assert created.status_code == 200
    backup_id = created.json()["backup_id"]

    agent_defs_dir = app.state.backup_service.resolve_target_path("config/agent-definitions")
    assert agent_defs_dir is not None
    (agent_defs_dir / "alpha.yaml").write_text("name: changed\n", encoding="utf-8")
    restore_plan = await async_client.post(
        f"/v1/backups/{backup_id}/restore-plan",
        headers=read_headers,
    )

    assert restore_plan.status_code == 200
    payload = restore_plan.json()
    assert payload["backup_id"] == backup_id
    assert any(asset["action"] == "overwrite" for asset in payload["assets_to_restore"])
    assert any(conflict["conflict_type"] == "file_modified" for conflict in payload["conflicts"])


@pytest.mark.asyncio()
async def test_backup_routes_restore_execute_requires_confirmation_and_restores(
    async_client: httpx.AsyncClient,
) -> None:
    write_headers = _auth_headers(scopes=["operator:write"])

    created = await async_client.post(
        "/v1/backups",
        json={"mode": "no-workspace", "label": "restore-api"},
        headers=write_headers,
    )
    assert created.status_code == 200
    backup_id = created.json()["backup_id"]

    packs_dir = app.state.backup_service.resolve_target_path("config/packs")
    assert packs_dir is not None

    shutil.rmtree(packs_dir)

    blocked = await async_client.post(
        f"/v1/backups/{backup_id}/restore",
        json={"confirm": False},
        headers=write_headers,
    )
    assert blocked.status_code == 409

    restored = await async_client.post(
        f"/v1/backups/{backup_id}/restore",
        json={"confirm": True},
        headers=write_headers,
    )

    assert restored.status_code == 200
    payload = restored.json()
    assert payload["success"] is True
    assert any(asset["relative_path"] == "config/packs" for asset in payload["restored_assets"])
    assert (packs_dir / "pack.yaml").read_text(encoding="utf-8") == "name: pack\n"
