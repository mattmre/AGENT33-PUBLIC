"""Repository abstraction for tenant-scoped workspaces and projects."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any, Protocol, runtime_checkable

from agent33.workspaces.models import WorkspaceProject, WorkspaceRecord


@runtime_checkable
class WorkspaceRepository(Protocol):
    """Protocol for workspace and project storage backends."""

    def list_workspaces(
        self,
        *,
        tenant_id: str | None = None,
        include_shared: bool = True,
    ) -> list[WorkspaceRecord]:
        """List workspaces visible to a tenant or all workspaces for admins."""
        ...

    def get_workspace(self, workspace_id: str) -> WorkspaceRecord | None:
        """Return one workspace by ID."""
        ...

    def create_workspace(self, workspace: WorkspaceRecord) -> WorkspaceRecord:
        """Create a workspace, raising ValueError on duplicate ID."""
        ...

    def update_workspace(self, workspace_id: str, changes: dict[str, Any]) -> WorkspaceRecord:
        """Patch a workspace, raising KeyError when missing."""
        ...

    def delete_workspace(self, workspace_id: str) -> bool:
        """Delete a workspace and its projects."""
        ...

    def list_projects(
        self,
        workspace_id: str,
        *,
        tenant_id: str | None = None,
    ) -> list[WorkspaceProject]:
        """List projects for a workspace, optionally tenant-filtered."""
        ...

    def get_project(self, workspace_id: str, project_id: str) -> WorkspaceProject | None:
        """Return one project by workspace and project ID."""
        ...

    def create_project(self, project: WorkspaceProject) -> WorkspaceProject:
        """Create a project under an existing workspace."""
        ...

    def update_project(
        self,
        workspace_id: str,
        project_id: str,
        changes: dict[str, Any],
    ) -> WorkspaceProject:
        """Patch a project, raising KeyError when missing."""
        ...

    def delete_project(self, workspace_id: str, project_id: str) -> bool:
        """Delete a project."""
        ...


class InMemoryWorkspaceRepository:
    """In-memory workspace repository with shared Phase 23 starter templates."""

    def __init__(self, *, seed_defaults: bool = True) -> None:
        self._workspaces: dict[str, WorkspaceRecord] = {}
        self._projects: dict[tuple[str, str], WorkspaceProject] = {}
        if seed_defaults:
            for workspace in _default_workspaces():
                self._workspaces[workspace.workspace_id] = workspace

    def list_workspaces(
        self,
        *,
        tenant_id: str | None = None,
        include_shared: bool = True,
    ) -> list[WorkspaceRecord]:
        items = list(self._workspaces.values())
        if tenant_id is not None:
            items = [
                workspace
                for workspace in items
                if workspace.tenant_id == tenant_id
                or (include_shared and workspace.tenant_id == "")
            ]
        return sorted(
            items,
            key=lambda item: (
                item.tenant_id != "",
                int(item.metadata.get("sort_order", 999)),
                item.created_at,
                item.name,
            ),
        )

    def get_workspace(self, workspace_id: str) -> WorkspaceRecord | None:
        return self._workspaces.get(workspace_id)

    def create_workspace(self, workspace: WorkspaceRecord) -> WorkspaceRecord:
        if workspace.workspace_id in self._workspaces:
            raise ValueError(f"Workspace {workspace.workspace_id} already exists")
        now = datetime.now(UTC)
        workspace.created_at = now
        workspace.updated_at = now
        self._workspaces[workspace.workspace_id] = workspace
        return workspace

    def update_workspace(self, workspace_id: str, changes: dict[str, Any]) -> WorkspaceRecord:
        workspace = self._workspaces.get(workspace_id)
        if workspace is None:
            raise KeyError(workspace_id)
        for key, value in changes.items():
            if value is not None and hasattr(workspace, key):
                setattr(workspace, key, value)
        workspace.updated_at = datetime.now(UTC)
        return workspace

    def delete_workspace(self, workspace_id: str) -> bool:
        if self._workspaces.pop(workspace_id, None) is None:
            return False
        for key in list(self._projects):
            if key[0] == workspace_id:
                del self._projects[key]
        return True

    def list_projects(
        self,
        workspace_id: str,
        *,
        tenant_id: str | None = None,
    ) -> list[WorkspaceProject]:
        items = [
            project
            for (stored_workspace_id, _project_id), project in self._projects.items()
            if stored_workspace_id == workspace_id
        ]
        if tenant_id is not None:
            items = [project for project in items if project.tenant_id == tenant_id]
        return sorted(items, key=lambda item: (item.status, item.created_at, item.name))

    def get_project(self, workspace_id: str, project_id: str) -> WorkspaceProject | None:
        return self._projects.get((workspace_id, project_id))

    def create_project(self, project: WorkspaceProject) -> WorkspaceProject:
        if project.workspace_id not in self._workspaces:
            raise KeyError(project.workspace_id)
        key = (project.workspace_id, project.project_id)
        if key in self._projects:
            raise ValueError(f"Project {project.project_id} already exists")
        now = datetime.now(UTC)
        project.created_at = now
        project.updated_at = now
        self._projects[key] = project
        workspace = self._workspaces[project.workspace_id]
        if project.project_id not in workspace.project_ids:
            workspace.project_ids.append(project.project_id)
            workspace.updated_at = now
        return project

    def update_project(
        self,
        workspace_id: str,
        project_id: str,
        changes: dict[str, Any],
    ) -> WorkspaceProject:
        project = self._projects.get((workspace_id, project_id))
        if project is None:
            raise KeyError(project_id)
        for key, value in changes.items():
            if value is not None and hasattr(project, key):
                setattr(project, key, value)
        project.updated_at = datetime.now(UTC)
        return project

    def delete_project(self, workspace_id: str, project_id: str) -> bool:
        if self._projects.pop((workspace_id, project_id), None) is None:
            return False
        workspace = self._workspaces.get(workspace_id)
        if workspace is not None and project_id in workspace.project_ids:
            workspace.project_ids.remove(project_id)
            workspace.updated_at = datetime.now(UTC)
        return True


class SqliteWorkspaceRepository:
    """SQLite-backed workspace repository for durable Phase 23 lifecycle state."""

    def __init__(self, db_path: str, *, seed_defaults: bool = True) -> None:
        self._db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = RLock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS phase23_workspaces ("
                "  workspace_id TEXT PRIMARY KEY,"
                "  tenant_id TEXT NOT NULL,"
                "  data TEXT NOT NULL"
                ")"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_phase23_workspaces_tenant "
                "ON phase23_workspaces(tenant_id)"
            )
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS phase23_workspace_projects ("
                "  workspace_id TEXT NOT NULL,"
                "  project_id TEXT NOT NULL,"
                "  tenant_id TEXT NOT NULL,"
                "  data TEXT NOT NULL,"
                "  PRIMARY KEY (workspace_id, project_id),"
                "  FOREIGN KEY (workspace_id) REFERENCES phase23_workspaces(workspace_id) "
                "  ON DELETE CASCADE"
                ")"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_phase23_workspace_projects_tenant "
                "ON phase23_workspace_projects(workspace_id, tenant_id)"
            )
            self._conn.commit()
        if seed_defaults:
            self._seed_default_workspaces()

    def list_workspaces(
        self,
        *,
        tenant_id: str | None = None,
        include_shared: bool = True,
    ) -> list[WorkspaceRecord]:
        with self._lock:
            if tenant_id is None:
                rows = self._conn.execute("SELECT data FROM phase23_workspaces").fetchall()
            elif include_shared:
                rows = self._conn.execute(
                    "SELECT data FROM phase23_workspaces WHERE tenant_id = ? OR tenant_id = ''",
                    (tenant_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT data FROM phase23_workspaces WHERE tenant_id = ?",
                    (tenant_id,),
                ).fetchall()
        items = [self._workspace_from_row(row) for row in rows]
        return sorted(
            items,
            key=lambda item: (
                item.tenant_id != "",
                int(item.metadata.get("sort_order", 999)),
                item.created_at,
                item.name,
            ),
        )

    def get_workspace(self, workspace_id: str) -> WorkspaceRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM phase23_workspaces WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()
        return None if row is None else self._workspace_from_row(row)

    def create_workspace(self, workspace: WorkspaceRecord) -> WorkspaceRecord:
        with self._lock:
            if self._workspace_exists(workspace.workspace_id):
                raise ValueError(f"Workspace {workspace.workspace_id} already exists")
            now = datetime.now(UTC)
            workspace.created_at = now
            workspace.updated_at = now
            self._upsert_workspace(workspace)
        return workspace

    def update_workspace(self, workspace_id: str, changes: dict[str, Any]) -> WorkspaceRecord:
        with self._lock:
            workspace = self._get_workspace_unlocked(workspace_id)
            if workspace is None:
                raise KeyError(workspace_id)
            for key, value in changes.items():
                if value is not None and hasattr(workspace, key):
                    setattr(workspace, key, value)
            workspace.updated_at = datetime.now(UTC)
            self._upsert_workspace(workspace)
        return workspace

    def delete_workspace(self, workspace_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM phase23_workspaces WHERE workspace_id = ?",
                (workspace_id,),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def list_projects(
        self,
        workspace_id: str,
        *,
        tenant_id: str | None = None,
    ) -> list[WorkspaceProject]:
        with self._lock:
            if tenant_id is None:
                rows = self._conn.execute(
                    "SELECT data FROM phase23_workspace_projects WHERE workspace_id = ?",
                    (workspace_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT data FROM phase23_workspace_projects "
                    "WHERE workspace_id = ? AND tenant_id = ?",
                    (workspace_id, tenant_id),
                ).fetchall()
        items = [self._project_from_row(row) for row in rows]
        return sorted(items, key=lambda item: (item.status, item.created_at, item.name))

    def get_project(self, workspace_id: str, project_id: str) -> WorkspaceProject | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM phase23_workspace_projects "
                "WHERE workspace_id = ? AND project_id = ?",
                (workspace_id, project_id),
            ).fetchone()
        return None if row is None else self._project_from_row(row)

    def create_project(self, project: WorkspaceProject) -> WorkspaceProject:
        with self._lock:
            workspace = self._get_workspace_unlocked(project.workspace_id)
            if workspace is None:
                raise KeyError(project.workspace_id)
            if self._project_exists(project.workspace_id, project.project_id):
                raise ValueError(f"Project {project.project_id} already exists")
            now = datetime.now(UTC)
            project.created_at = now
            project.updated_at = now
            self._upsert_project(project)
            if project.project_id not in workspace.project_ids:
                workspace.project_ids.append(project.project_id)
                workspace.updated_at = now
                self._upsert_workspace(workspace)
        return project

    def update_project(
        self,
        workspace_id: str,
        project_id: str,
        changes: dict[str, Any],
    ) -> WorkspaceProject:
        with self._lock:
            project = self._get_project_unlocked(workspace_id, project_id)
            if project is None:
                raise KeyError(project_id)
            for key, value in changes.items():
                if value is not None and hasattr(project, key):
                    setattr(project, key, value)
            project.updated_at = datetime.now(UTC)
            self._upsert_project(project)
        return project

    def delete_project(self, workspace_id: str, project_id: str) -> bool:
        with self._lock:
            if not self._project_exists(workspace_id, project_id):
                return False
            self._conn.execute(
                "DELETE FROM phase23_workspace_projects "
                "WHERE workspace_id = ? AND project_id = ?",
                (workspace_id, project_id),
            )
            workspace = self._get_workspace_unlocked(workspace_id)
            if workspace is not None and project_id in workspace.project_ids:
                workspace.project_ids.remove(project_id)
                workspace.updated_at = datetime.now(UTC)
                self._upsert_workspace(workspace)
            self._conn.commit()
            return True

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _seed_default_workspaces(self) -> None:
        with self._lock:
            for workspace in _default_workspaces():
                if not self._workspace_exists(workspace.workspace_id):
                    self._upsert_workspace(workspace)

    def _workspace_exists(self, workspace_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM phase23_workspaces WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
        return row is not None

    def _project_exists(self, workspace_id: str, project_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM phase23_workspace_projects "
            "WHERE workspace_id = ? AND project_id = ?",
            (workspace_id, project_id),
        ).fetchone()
        return row is not None

    def _get_workspace_unlocked(self, workspace_id: str) -> WorkspaceRecord | None:
        row = self._conn.execute(
            "SELECT data FROM phase23_workspaces WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
        return None if row is None else self._workspace_from_row(row)

    def _get_project_unlocked(
        self,
        workspace_id: str,
        project_id: str,
    ) -> WorkspaceProject | None:
        row = self._conn.execute(
            "SELECT data FROM phase23_workspace_projects "
            "WHERE workspace_id = ? AND project_id = ?",
            (workspace_id, project_id),
        ).fetchone()
        return None if row is None else self._project_from_row(row)

    def _upsert_workspace(self, workspace: WorkspaceRecord) -> None:
        self._conn.execute(
            "INSERT INTO phase23_workspaces (workspace_id, tenant_id, data) VALUES (?, ?, ?) "
            "ON CONFLICT(workspace_id) DO UPDATE SET "
            "tenant_id = excluded.tenant_id, data = excluded.data",
            (
                workspace.workspace_id,
                workspace.tenant_id,
                json.dumps(workspace.to_dict(), sort_keys=True),
            ),
        )
        self._conn.commit()

    def _upsert_project(self, project: WorkspaceProject) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO phase23_workspace_projects "
            "(workspace_id, project_id, tenant_id, data) VALUES (?, ?, ?, ?)",
            (
                project.workspace_id,
                project.project_id,
                project.tenant_id,
                json.dumps(project.to_dict(), sort_keys=True),
            ),
        )
        self._conn.commit()

    @staticmethod
    def _workspace_from_row(row: sqlite3.Row) -> WorkspaceRecord:
        data = json.loads(row["data"])
        if not isinstance(data, dict):
            raise ValueError("Invalid workspace repository record")
        return WorkspaceRecord.from_dict(data)

    @staticmethod
    def _project_from_row(row: sqlite3.Row) -> WorkspaceProject:
        data = json.loads(row["data"])
        if not isinstance(data, dict):
            raise ValueError("Invalid workspace project repository record")
        return WorkspaceProject.from_dict(data)


def _default_workspaces() -> list[WorkspaceRecord]:
    defaults = [
        (
            "solo-builder",
            "Local Shipyard",
            "Solo Builder",
            "Turn a plain-language idea into a guided build plan.",
            "Ready",
            2,
            3,
        ),
        (
            "research-build",
            "Research Sprint",
            "Research + Build",
            "Collect evidence, compare options, and convert findings into implementation tasks.",
            "Planning",
            3,
            4,
        ),
        (
            "test-review",
            "Quality Gate",
            "Test + Review",
            "Validate changes, review artifacts, and prepare a merge-ready handoff.",
            "Ready",
            2,
            4,
        ),
        (
            "shipyard",
            "Multi-Agent Shipyard",
            "Multi-Agent Shipyard",
            "Coordinate scout, builder, reviewer, and operator lanes for larger work.",
            "Running",
            4,
            5,
        ),
    ]
    return [
        WorkspaceRecord(
            workspace_id=workspace_id,
            name=name,
            template=template,
            goal=goal,
            status=status,
            tenant_id="",
            owner="system",
            agents=agents,
            tasks=tasks,
            metadata={"source": "phase23-default-template", "sort_order": index},
        )
        for index, (workspace_id, name, template, goal, status, agents, tasks) in enumerate(
            defaults,
        )
    ]


_repository: WorkspaceRepository | None = None


def get_workspace_repository() -> WorkspaceRepository:
    """Return the configured workspace repository."""
    global _repository  # noqa: PLW0603
    if _repository is None:
        _repository = InMemoryWorkspaceRepository()
    return _repository


def set_workspace_repository(repo: WorkspaceRepository) -> None:
    """Set the process-wide workspace repository."""
    global _repository  # noqa: PLW0603
    _repository = repo
