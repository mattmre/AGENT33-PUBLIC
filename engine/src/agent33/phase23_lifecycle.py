"""Phase 23 durable lifecycle repository wiring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from agent33.security.auth_repository import (
    AuthRepository,
    InMemoryAuthRepository,
    SqliteAuthRepository,
    get_auth_repository,
    set_auth_repository,
)
from agent33.workspaces.repository import (
    SqliteWorkspaceRepository,
    WorkspaceRepository,
    get_workspace_repository,
    set_workspace_repository,
)

if TYPE_CHECKING:
    from agent33.state_paths import RuntimeStatePaths


@dataclass(frozen=True, slots=True)
class Phase23LifecycleRepositories:
    """Installed Phase 23 lifecycle repositories and their backend metadata."""

    backend: str
    auth_repository: AuthRepository
    workspace_repository: WorkspaceRepository
    auth_db_path: str
    workspace_db_path: str
    previous_auth_repository: AuthRepository | None = None
    previous_workspace_repository: WorkspaceRepository | None = None

    def close(self) -> None:
        for repo in (self.auth_repository, self.workspace_repository):
            close = getattr(repo, "close", None)
            if callable(close):
                close()
        if self.previous_auth_repository is not None:
            set_auth_repository(self.previous_auth_repository)
        if self.previous_workspace_repository is not None:
            set_workspace_repository(self.previous_workspace_repository)


def install_phase23_lifecycle_repositories(
    settings: Any,
    state_paths: RuntimeStatePaths,
) -> Phase23LifecycleRepositories:
    """Install runtime repositories for Phase 23 auth/workspace lifecycle state."""
    backend = str(settings.phase23_lifecycle_backend).strip().lower()
    if backend == "memory":
        return Phase23LifecycleRepositories(
            backend="memory",
            auth_repository=get_auth_repository(),
            workspace_repository=get_workspace_repository(),
            auth_db_path="",
            workspace_db_path="",
        )

    auth_path = state_paths.resolve_approved(settings.phase23_auth_db_path)
    workspace_path = state_paths.resolve_approved(settings.phase23_workspace_db_path)
    previous_auth_repo = get_auth_repository()
    previous_workspace_repo = get_workspace_repository()

    auth_repo = SqliteAuthRepository(str(auth_path))
    _copy_auth_repository(previous_auth_repo, auth_repo)
    set_auth_repository(auth_repo)

    workspace_repo = SqliteWorkspaceRepository(str(workspace_path))
    _copy_workspace_repository(previous_workspace_repo, workspace_repo)
    set_workspace_repository(workspace_repo)

    return Phase23LifecycleRepositories(
        backend="sqlite",
        auth_repository=auth_repo,
        workspace_repository=workspace_repo,
        auth_db_path=str(auth_path),
        workspace_db_path=str(workspace_path),
        previous_auth_repository=previous_auth_repo,
        previous_workspace_repository=previous_workspace_repo,
    )


def _copy_auth_repository(source: AuthRepository, target: SqliteAuthRepository) -> None:
    if source is target:
        return
    for user in source.list_users():
        username = str(user.get("username", ""))
        if username:
            target.set_user(username, dict(user))
    if isinstance(source, InMemoryAuthRepository):
        for key_hash, record in source._api_keys.items():
            target.set_api_key(key_hash, dict(record))


def _copy_workspace_repository(
    source: WorkspaceRepository,
    target: SqliteWorkspaceRepository,
) -> None:
    if source is target:
        return
    for workspace in source.list_workspaces():
        if target.get_workspace(workspace.workspace_id) is None:
            target.create_workspace(workspace)
        for project in source.list_projects(workspace.workspace_id):
            if target.get_project(project.workspace_id, project.project_id) is None:
                target.create_project(project)
