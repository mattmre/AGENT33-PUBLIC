"""Phase 23 workspace, project, and recovery APIs."""

from __future__ import annotations

from datetime import datetime  # noqa: TCH003 -- Pydantic needs runtime type
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from agent33.api.route_approvals import require_route_mutation_approval
from agent33.api.routes.tenant_access import require_tenant_context, tenant_filter_for_request
from agent33.security.permissions import check_permission, require_scope
from agent33.sessions.models import OperatorSessionStatus
from agent33.tools.approvals import ApprovalRiskTier
from agent33.workspaces.models import (
    WorkspaceProject,
    WorkspaceProjectStatus,
    WorkspaceRecord,
    WorkspaceStatus,
)
from agent33.workspaces.repository import WorkspaceRepository, get_workspace_repository

router = APIRouter(prefix="/v1/workspaces", tags=["workspaces"])


class WorkspaceCreateRequest(BaseModel):
    """Body for creating a workspace."""

    workspace_id: str | None = Field(default=None, min_length=1, max_length=80)
    name: str = Field(..., min_length=1, max_length=160)
    template: str = Field(default="", max_length=160)
    goal: str = Field(default="", max_length=500)
    status: WorkspaceStatus = "Ready"
    tenant_id: str = Field(default="", max_length=120)
    owner: str = Field(default="", max_length=160)
    agents: int = Field(default=0, ge=0)
    tasks: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkspaceUpdateRequest(BaseModel):
    """Body for patching a workspace."""

    name: str | None = Field(default=None, min_length=1, max_length=160)
    template: str | None = Field(default=None, max_length=160)
    goal: str | None = Field(default=None, max_length=500)
    status: WorkspaceStatus | None = None
    tenant_id: str | None = Field(default=None, max_length=120)
    owner: str | None = Field(default=None, max_length=160)
    agents: int | None = Field(default=None, ge=0)
    tasks: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] | None = None


class WorkspaceResponse(BaseModel):
    """Serialized workspace response."""

    workspace_id: str
    id: str
    name: str
    template: str
    goal: str
    status: WorkspaceStatus
    tenant_id: str
    owner: str
    agents: int
    tasks: int
    project_ids: list[str]
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ProjectCreateRequest(BaseModel):
    """Body for creating a workspace project."""

    project_id: str | None = Field(default=None, min_length=1, max_length=80)
    name: str = Field(..., min_length=1, max_length=160)
    status: WorkspaceProjectStatus = "active"
    owner: str = Field(default="", max_length=160)
    session_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectUpdateRequest(BaseModel):
    """Body for patching a workspace project."""

    name: str | None = Field(default=None, min_length=1, max_length=160)
    status: WorkspaceProjectStatus | None = None
    owner: str | None = Field(default=None, max_length=160)
    session_ids: list[str] | None = None
    metadata: dict[str, Any] | None = None


class ProjectResponse(BaseModel):
    """Serialized workspace project response."""

    project_id: str
    workspace_id: str
    name: str
    status: WorkspaceProjectStatus
    tenant_id: str
    owner: str
    session_ids: list[str]
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class WorkspaceRecoverySnapshot(BaseModel):
    """One recoverable workspace checkpoint."""

    id: str
    label: str
    status: Literal["ready", "attention", "blocked"]
    resume_action: str
    rollback_action: str
    budget_label: str
    artifact_count: int
    source: Literal["session", "project"]


class WorkspaceRecoveryResponse(BaseModel):
    """Recovery summary for a workspace."""

    workspace_id: str
    primary_message: str
    next_action: str
    snapshots: list[WorkspaceRecoverySnapshot]


WorkspaceResponse.model_rebuild()
ProjectResponse.model_rebuild()


def _repo() -> WorkspaceRepository:
    return get_workspace_repository()


def _request_context(request: Request) -> tuple[str, list[str], bool]:
    tenant_id, scopes = require_tenant_context(request)
    return tenant_id, scopes, check_permission("admin", scopes) if scopes else False


def _workspace_to_response(workspace: WorkspaceRecord) -> WorkspaceResponse:
    payload = workspace.to_dict()
    payload["id"] = workspace.workspace_id
    return WorkspaceResponse(**payload)


def _project_to_response(project: WorkspaceProject) -> ProjectResponse:
    return ProjectResponse(**project.to_dict())


def _tenant_can_read(workspace: WorkspaceRecord, tenant_id: str | None, is_admin: bool) -> bool:
    if is_admin:
        return True
    return workspace.tenant_id == "" or (
        tenant_id is not None and workspace.tenant_id == tenant_id
    )


def _tenant_can_mutate(workspace: WorkspaceRecord, tenant_id: str, is_admin: bool) -> bool:
    if is_admin:
        return True
    return workspace.tenant_id == tenant_id


def _get_visible_workspace(request: Request, workspace_id: str) -> tuple[WorkspaceRecord, bool]:
    tenant_id, _scopes, is_admin = _request_context(request)
    workspace = _repo().get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found")
    if not _tenant_can_read(workspace, tenant_id or None, is_admin):
        raise HTTPException(status_code=403, detail="Tenant mismatch")
    return workspace, is_admin


def _require_mutable_workspace(
    request: Request,
    workspace_id: str,
) -> tuple[WorkspaceRecord, bool]:
    tenant_id, _scopes, is_admin = _request_context(request)
    workspace = _repo().get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found")
    if not _tenant_can_mutate(workspace, tenant_id, is_admin):
        raise HTTPException(status_code=403, detail="Workspace is read-only for this tenant")
    return workspace, is_admin


def _project_tenant_filter(
    workspace: WorkspaceRecord,
    tenant_id: str,
    is_admin: bool,
) -> str | None:
    if is_admin:
        return None
    if workspace.tenant_id == "":
        return tenant_id
    return workspace.tenant_id


def _approval_arguments(body: BaseModel, **extra: Any) -> dict[str, Any]:
    arguments = body.model_dump(mode="json", exclude_none=True)
    arguments.update(extra)
    return arguments


@router.get("/", dependencies=[require_scope("workspaces:read")])
async def list_workspaces(
    request: Request,
    include_shared: bool = Query(default=True),
) -> list[WorkspaceResponse]:
    """List workspaces visible to the current tenant."""
    tenant_id = tenant_filter_for_request(request)
    workspaces = _repo().list_workspaces(
        tenant_id=tenant_id,
        include_shared=include_shared,
    )
    return [_workspace_to_response(workspace) for workspace in workspaces]


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_scope("workspaces:write")],
)
async def create_workspace(body: WorkspaceCreateRequest, request: Request) -> WorkspaceResponse:
    """Create a tenant-owned workspace."""
    require_route_mutation_approval(
        request,
        route_name="workspaces.create",
        operation="create",
        arguments=_approval_arguments(body),
        details="Workspace creation changes tenant lifecycle state.",
        risk_tier=ApprovalRiskTier.MEDIUM,
    )
    tenant_id, _scopes, is_admin = _request_context(request)
    effective_tenant_id = body.tenant_id if is_admin else tenant_id
    workspace = WorkspaceRecord(
        workspace_id=body.workspace_id or "",
        name=body.name,
        template=body.template,
        goal=body.goal,
        status=body.status,
        tenant_id=effective_tenant_id,
        owner=body.owner,
        agents=body.agents,
        tasks=body.tasks,
        metadata=body.metadata,
    )
    if workspace.workspace_id == "":
        workspace.workspace_id = workspace.name.lower().replace(" ", "-")[:80]
    try:
        created = _repo().create_workspace(workspace)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _workspace_to_response(created)


@router.get("/{workspace_id}", dependencies=[require_scope("workspaces:read")])
async def get_workspace(workspace_id: str, request: Request) -> WorkspaceResponse:
    """Return one workspace."""
    workspace, _is_admin = _get_visible_workspace(request, workspace_id)
    return _workspace_to_response(workspace)


@router.patch("/{workspace_id}", dependencies=[require_scope("workspaces:write")])
async def update_workspace(
    workspace_id: str,
    body: WorkspaceUpdateRequest,
    request: Request,
) -> WorkspaceResponse:
    """Patch a workspace."""
    workspace, is_admin = _require_mutable_workspace(request, workspace_id)
    require_route_mutation_approval(
        request,
        route_name="workspaces.update",
        operation="update",
        arguments=_approval_arguments(body, workspace_id=workspace_id),
        details="Workspace updates require explicit operator approval.",
        risk_tier=ApprovalRiskTier.MEDIUM,
    )
    changes = body.model_dump(exclude_none=True)
    if "tenant_id" in changes and not is_admin:
        changes.pop("tenant_id")
    if workspace.tenant_id == "" and not is_admin:
        raise HTTPException(status_code=403, detail="Shared workspace templates are read-only")
    return _workspace_to_response(_repo().update_workspace(workspace_id, changes))


@router.delete(
    "/{workspace_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require_scope("workspaces:write")],
    response_model=None,
)
async def delete_workspace(workspace_id: str, request: Request) -> None:
    """Delete a mutable workspace and its projects."""
    workspace, is_admin = _require_mutable_workspace(request, workspace_id)
    require_route_mutation_approval(
        request,
        route_name="workspaces.delete",
        operation="delete",
        arguments={"workspace_id": workspace_id},
        details="Workspace deletion removes tenant lifecycle state.",
        risk_tier=ApprovalRiskTier.HIGH,
    )
    if workspace.tenant_id == "" and not is_admin:
        raise HTTPException(status_code=403, detail="Shared workspace templates cannot be deleted")
    if not _repo().delete_workspace(workspace_id):
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found")


@router.get("/{workspace_id}/projects", dependencies=[require_scope("workspaces:read")])
async def list_workspace_projects(
    workspace_id: str,
    request: Request,
) -> list[ProjectResponse]:
    """List projects for a workspace."""
    tenant_id, _scopes, is_admin = _request_context(request)
    workspace, _is_admin = _get_visible_workspace(request, workspace_id)
    projects = _repo().list_projects(
        workspace_id,
        tenant_id=_project_tenant_filter(workspace, tenant_id, is_admin),
    )
    return [_project_to_response(project) for project in projects]


@router.post(
    "/{workspace_id}/projects",
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_scope("workspaces:write")],
)
async def create_workspace_project(
    workspace_id: str,
    body: ProjectCreateRequest,
    request: Request,
) -> ProjectResponse:
    """Create a tenant-owned project under a workspace."""
    tenant_id, _scopes, is_admin = _request_context(request)
    workspace, _is_admin = _get_visible_workspace(request, workspace_id)
    require_route_mutation_approval(
        request,
        route_name="workspaces.projects.create",
        operation="create",
        arguments=_approval_arguments(body, workspace_id=workspace_id),
        details="Workspace project creation changes tenant lifecycle state.",
        risk_tier=ApprovalRiskTier.MEDIUM,
    )
    project = WorkspaceProject(
        project_id=body.project_id or "",
        workspace_id=workspace_id,
        name=body.name,
        status=body.status,
        tenant_id=workspace.tenant_id or tenant_id,
        owner=body.owner,
        session_ids=body.session_ids,
        metadata=body.metadata,
    )
    if project.project_id == "":
        project.project_id = project.name.lower().replace(" ", "-")[:80]
    if not _tenant_can_mutate(WorkspaceRecord(tenant_id=project.tenant_id), tenant_id, is_admin):
        raise HTTPException(status_code=403, detail="Tenant mismatch")
    try:
        created = _repo().create_project(project)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _project_to_response(created)


@router.patch(
    "/{workspace_id}/projects/{project_id}",
    dependencies=[require_scope("workspaces:write")],
)
async def update_workspace_project(
    workspace_id: str,
    project_id: str,
    body: ProjectUpdateRequest,
    request: Request,
) -> ProjectResponse:
    """Patch a workspace project."""
    tenant_id, _scopes, is_admin = _request_context(request)
    workspace, _is_admin = _get_visible_workspace(request, workspace_id)
    project = _repo().get_project(workspace_id, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    if _project_tenant_filter(workspace, tenant_id, is_admin) not in (None, project.tenant_id):
        raise HTTPException(status_code=403, detail="Tenant mismatch")
    require_route_mutation_approval(
        request,
        route_name="workspaces.projects.update",
        operation="update",
        arguments=_approval_arguments(body, workspace_id=workspace_id, project_id=project_id),
        details="Workspace project updates require explicit operator approval.",
        risk_tier=ApprovalRiskTier.MEDIUM,
    )
    updated = _repo().update_project(workspace_id, project_id, body.model_dump(exclude_none=True))
    return _project_to_response(updated)


@router.delete(
    "/{workspace_id}/projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require_scope("workspaces:write")],
    response_model=None,
)
async def delete_workspace_project(
    workspace_id: str,
    project_id: str,
    request: Request,
) -> None:
    """Delete a workspace project."""
    tenant_id, _scopes, is_admin = _request_context(request)
    workspace, _is_admin = _get_visible_workspace(request, workspace_id)
    project = _repo().get_project(workspace_id, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    if _project_tenant_filter(workspace, tenant_id, is_admin) not in (None, project.tenant_id):
        raise HTTPException(status_code=403, detail="Tenant mismatch")
    require_route_mutation_approval(
        request,
        route_name="workspaces.projects.delete",
        operation="delete",
        arguments={"workspace_id": workspace_id, "project_id": project_id},
        details="Workspace project deletion removes tenant lifecycle state.",
        risk_tier=ApprovalRiskTier.HIGH,
    )
    if not _repo().delete_project(workspace_id, project_id):
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")


@router.get("/{workspace_id}/recovery", dependencies=[require_scope("workspaces:read")])
async def get_workspace_recovery(
    workspace_id: str,
    request: Request,
) -> WorkspaceRecoveryResponse:
    """Return live recovery checkpoints from workspace projects and sessions."""
    tenant_id, _scopes, is_admin = _request_context(request)
    workspace, _is_admin = _get_visible_workspace(request, workspace_id)
    snapshots = await _session_recovery_snapshots(request, workspace_id, tenant_id, is_admin)
    for project in _repo().list_projects(
        workspace_id,
        tenant_id=_project_tenant_filter(workspace, tenant_id, is_admin),
    ):
        if project.status in {"blocked", "paused"}:
            snapshots.append(
                WorkspaceRecoverySnapshot(
                    id=project.project_id,
                    label=project.name,
                    status="blocked" if project.status == "blocked" else "attention",
                    resume_action="Resume project",
                    rollback_action="Review last project checkpoint",
                    budget_label=f"{len(project.session_ids)} sessions",
                    artifact_count=len(project.metadata.get("artifacts", [])),
                    source="project",
                )
            )
    return _recovery_response(workspace_id, snapshots)


async def _session_recovery_snapshots(
    request: Request,
    workspace_id: str,
    tenant_id: str,
    is_admin: bool,
) -> list[WorkspaceRecoverySnapshot]:
    service = getattr(request.app.state, "operator_session_service", None)
    if service is None:
        return []
    session_tenant = None if is_admin else tenant_id
    sessions = await service.list_sessions(status=None, limit=200, tenant_id=session_tenant)
    snapshots: list[WorkspaceRecoverySnapshot] = []
    for session in sessions:
        context = dict(getattr(session, "context", {}) or {})
        if context.get("workspace_id") != workspace_id:
            continue
        status_value = _session_status_value(getattr(session, "status", "active"))
        if status_value not in {
            OperatorSessionStatus.ACTIVE.value,
            OperatorSessionStatus.SUSPENDED.value,
            OperatorSessionStatus.CRASHED.value,
        }:
            continue
        snapshots.append(
            WorkspaceRecoverySnapshot(
                id=str(getattr(session, "session_id", "")),
                label=str(getattr(session, "purpose", "") or "Workspace session"),
                status=_recovery_status_for_session(status_value),
                resume_action="Resume session",
                rollback_action="Restore latest checkpoint",
                budget_label=(
                    f"{getattr(session, 'task_count', 0)} tasks / "
                    f"{getattr(session, 'event_count', 0)} events"
                ),
                artifact_count=len(context.get("artifacts", [])),
                source="session",
            )
        )
    return snapshots


def _session_status_value(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _recovery_status_for_session(status_value: str) -> Literal["ready", "attention", "blocked"]:
    if status_value == OperatorSessionStatus.CRASHED.value:
        return "blocked"
    if status_value == OperatorSessionStatus.SUSPENDED.value:
        return "ready"
    return "attention"


def _recovery_response(
    workspace_id: str,
    snapshots: list[WorkspaceRecoverySnapshot],
) -> WorkspaceRecoveryResponse:
    if not snapshots:
        return WorkspaceRecoveryResponse(
            workspace_id=workspace_id,
            primary_message="No live recovery checkpoints are currently open.",
            next_action="Start or resume a workspace session to create a recoverable checkpoint.",
            snapshots=[],
        )
    blocked = sum(1 for snapshot in snapshots if snapshot.status == "blocked")
    if blocked:
        primary = f"{blocked} recovery checkpoint requires attention."
        next_action = "Review blocked checkpoints before starting new workspace work."
    else:
        primary = f"{len(snapshots)} recovery checkpoint is ready."
        if len(snapshots) != 1:
            primary = f"{len(snapshots)} recovery checkpoints are ready."
        next_action = "Resume the most recent checkpoint or continue workspace execution."
    return WorkspaceRecoveryResponse(
        workspace_id=workspace_id,
        primary_message=primary,
        next_action=next_action,
        snapshots=snapshots,
    )
