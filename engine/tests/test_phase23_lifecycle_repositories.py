"""Phase 23 durable lifecycle repository wiring tests."""

from __future__ import annotations

from agent33.config import Settings
from agent33.phase23_lifecycle import install_phase23_lifecycle_repositories
from agent33.security.auth_repository import (
    InMemoryAuthRepository,
    get_auth_repository,
    set_auth_repository,
)
from agent33.state_paths import RuntimeStatePaths
from agent33.workspaces.models import WorkspaceRecord
from agent33.workspaces.repository import (
    InMemoryWorkspaceRepository,
    get_workspace_repository,
    set_workspace_repository,
)


def test_phase23_lifecycle_defaults_to_sqlite_backend() -> None:
    settings = Settings()

    assert settings.phase23_lifecycle_backend == "sqlite"
    assert settings.phase23_auth_db_path == "var/phase23_auth_lifecycle.db"
    assert settings.phase23_workspace_db_path == "var/phase23_workspace_lifecycle.db"


def test_phase23_sqlite_install_migrates_process_local_state(tmp_path) -> None:
    auth_memory = InMemoryAuthRepository()
    auth_memory.create_user(
        username="alice",
        password_hash="hash",
        tenant_id="tenant-a",
        scopes=["workspaces:read"],
    )
    auth_memory.create_api_key(
        key_hash="hash1",
        key_id="key-1",
        subject="alice",
        scopes=["workspaces:read"],
        tenant_id="tenant-a",
    )

    workspace_memory = InMemoryWorkspaceRepository(seed_defaults=False)
    workspace_memory.create_workspace(
        WorkspaceRecord(
            workspace_id="tenant-a-build",
            name="Tenant A Build",
            tenant_id="tenant-a",
        )
    )

    previous_auth = get_auth_repository()
    previous_workspace = get_workspace_repository()
    set_auth_repository(auth_memory)
    set_workspace_repository(workspace_memory)
    settings = Settings(
        phase23_auth_db_path="var/test-phase23-auth.db",
        phase23_workspace_db_path="var/test-phase23-workspaces.db",
    )
    state_paths = RuntimeStatePaths.from_app_root(tmp_path, home_dir=tmp_path)

    installed = install_phase23_lifecycle_repositories(settings, state_paths)
    try:
        assert installed.backend == "sqlite"
        assert get_auth_repository().get_user("alice") is not None
        assert get_auth_repository().get_api_key("hash1") is not None
        assert get_workspace_repository().get_workspace("tenant-a-build") is not None
    finally:
        installed.close()
        set_auth_repository(previous_auth)
        set_workspace_repository(previous_workspace)
