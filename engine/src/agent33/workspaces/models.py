"""Workspace and project storage models for Phase 23 lifecycle APIs."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

WorkspaceStatus = Literal["Ready", "Planning", "Running", "Archived"]
WorkspaceProjectStatus = Literal["active", "paused", "blocked", "complete", "archived"]


@dataclasses.dataclass
class WorkspaceProject:
    """A tenant-owned project nested under a workspace."""

    project_id: str = dataclasses.field(default_factory=lambda: uuid4().hex[:12])
    workspace_id: str = ""
    name: str = ""
    status: WorkspaceProjectStatus = "active"
    tenant_id: str = ""
    owner: str = ""
    session_ids: list[str] = dataclasses.field(default_factory=list)
    metadata: dict[str, Any] = dataclasses.field(default_factory=dict)
    created_at: datetime = dataclasses.field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = dataclasses.field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Serialize the project to a JSON-friendly dict."""
        return {
            "project_id": self.project_id,
            "workspace_id": self.workspace_id,
            "name": self.name,
            "status": self.status,
            "tenant_id": self.tenant_id,
            "owner": self.owner,
            "session_ids": list(self.session_ids),
            "metadata": dict(self.metadata),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkspaceProject:
        """Deserialize a project from storage."""
        return cls(
            project_id=str(data.get("project_id", uuid4().hex[:12])),
            workspace_id=str(data.get("workspace_id", "")),
            name=str(data.get("name", "")),
            status=_project_status(data.get("status", "active")),
            tenant_id=str(data.get("tenant_id", "")),
            owner=str(data.get("owner", "")),
            session_ids=[str(item) for item in data.get("session_ids", [])],
            metadata=dict(data.get("metadata", {})),
            created_at=_parse_datetime(data.get("created_at")),
            updated_at=_parse_datetime(data.get("updated_at")),
        )


@dataclasses.dataclass
class WorkspaceRecord:
    """A workspace visible in the cockpit and scoped to a tenant or template."""

    workspace_id: str = dataclasses.field(default_factory=lambda: uuid4().hex[:12])
    name: str = ""
    template: str = ""
    goal: str = ""
    status: WorkspaceStatus = "Ready"
    tenant_id: str = ""
    owner: str = ""
    agents: int = 0
    tasks: int = 0
    project_ids: list[str] = dataclasses.field(default_factory=list)
    metadata: dict[str, Any] = dataclasses.field(default_factory=dict)
    created_at: datetime = dataclasses.field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = dataclasses.field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Serialize the workspace to a JSON-friendly dict."""
        return {
            "workspace_id": self.workspace_id,
            "name": self.name,
            "template": self.template,
            "goal": self.goal,
            "status": self.status,
            "tenant_id": self.tenant_id,
            "owner": self.owner,
            "agents": self.agents,
            "tasks": self.tasks,
            "project_ids": list(self.project_ids),
            "metadata": dict(self.metadata),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkspaceRecord:
        """Deserialize a workspace from storage."""
        return cls(
            workspace_id=str(data.get("workspace_id", uuid4().hex[:12])),
            name=str(data.get("name", "")),
            template=str(data.get("template", "")),
            goal=str(data.get("goal", "")),
            status=_workspace_status(data.get("status", "Ready")),
            tenant_id=str(data.get("tenant_id", "")),
            owner=str(data.get("owner", "")),
            agents=int(data.get("agents", 0)),
            tasks=int(data.get("tasks", 0)),
            project_ids=[str(item) for item in data.get("project_ids", [])],
            metadata=dict(data.get("metadata", {})),
            created_at=_parse_datetime(data.get("created_at")),
            updated_at=_parse_datetime(data.get("updated_at")),
        )


def _parse_datetime(value: Any) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise ValueError("Invalid datetime value")


def _workspace_status(value: Any) -> WorkspaceStatus:
    if value in {"Ready", "Planning", "Running", "Archived"}:
        return value
    raise ValueError(f"Invalid workspace status: {value}")


def _project_status(value: Any) -> WorkspaceProjectStatus:
    if value in {"active", "paused", "blocked", "complete", "archived"}:
        return value
    raise ValueError(f"Invalid workspace project status: {value}")
