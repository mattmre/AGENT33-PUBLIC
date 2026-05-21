"""FastAPI routes for managed background processes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from agent33.processes.models import (
    ManagedProcessCleanupResponse,
    ManagedProcessListResponse,
    ManagedProcessLogResponse,
    ManagedProcessRecord,
)
from agent33.processes.service import (
    ManagedProcessNotFoundError,
    ProcessLimitError,
    ProcessManagerService,
    ProcessValidationError,
)
from agent33.security.permissions import require_scope
from agent33.tools.base import ToolContext

if TYPE_CHECKING:
    from agent33.tools.governance import ToolGovernance

router = APIRouter(prefix="/v1/processes", tags=["processes"])


class StartProcessRequest(BaseModel):
    """Request body for starting a managed process."""

    command: str
    working_dir: str = ""
    environment: dict[str, str] = Field(default_factory=dict)
    agent_id: str = ""
    session_id: str = ""


class WriteProcessInputRequest(BaseModel):
    """Request body for writing to process stdin."""

    data: str


class CleanupProcessesRequest(BaseModel):
    """Request body for cleanup of completed processes."""

    max_age_seconds: int = 3600


def get_process_manager_service(request: Request) -> ProcessManagerService:
    """Return the app-scoped process manager service."""
    svc: ProcessManagerService | None = getattr(request.app.state, "process_manager_service", None)
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Process manager service not initialized",
        )
    return svc


ProcessManagerDependency = Annotated[ProcessManagerService, Depends(get_process_manager_service)]


def _tenant_id(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if user is None:
        return ""
    return getattr(user, "tenant_id", "") or ""


def _requested_by(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if user is None:
        return ""
    return getattr(user, "sub", "") or ""


def _ensure_governed_process_start(
    request: Request,
    svc: ProcessManagerService,
    command: str,
    working_dir: str,
    session_id: str,
) -> None:
    governance: ToolGovernance | None = getattr(request.app.state, "tool_governance", None)
    user = getattr(request.state, "user", None)
    if governance is None or user is None:
        return
    resolved_root = svc.workspace_root
    context = ToolContext(
        user_scopes=list(getattr(user, "scopes", [])),
        path_allowlist=[str(resolved_root)],
        working_dir=resolved_root,
        requested_by=getattr(user, "sub", "") or "",
        tenant_id=getattr(user, "tenant_id", "") or "",
        session_id=session_id,
    )
    allowed = governance.pre_execute_check(
        "shell",
        {"command": command, "working_dir": working_dir, "operation": "start"},
        context,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Process start blocked by tool governance",
        )


@router.get(
    "",
    response_model=ManagedProcessListResponse,
    dependencies=[require_scope("processes:read")],
)
async def list_processes(
    request: Request,
    svc: ProcessManagerDependency,
    session_id: str = "",
    status_filter: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> ManagedProcessListResponse:
    """List visible managed processes."""
    tenant_id = _tenant_id(request)
    processes = svc.list_processes(
        tenant_id=tenant_id,
        session_id=session_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    total = svc.count_processes(tenant_id=tenant_id, session_id=session_id, status=status_filter)
    return ManagedProcessListResponse(processes=processes, count=len(processes), total=total)


@router.post(
    "",
    response_model=ManagedProcessRecord,
    dependencies=[require_scope("processes:manage")],
)
async def start_process(
    request: Request,
    body: StartProcessRequest,
    svc: ProcessManagerDependency,
) -> ManagedProcessRecord:
    """Start a governed managed process."""
    _ensure_governed_process_start(request, svc, body.command, body.working_dir, body.session_id)
    try:
        return await svc.start(
            body.command,
            working_dir=body.working_dir,
            environment=body.environment,
            agent_id=body.agent_id,
            session_id=body.session_id,
            tenant_id=_tenant_id(request),
            requested_by=_requested_by(request),
        )
    except (ProcessValidationError, ProcessLimitError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/cleanup",
    response_model=ManagedProcessCleanupResponse,
    dependencies=[require_scope("processes:manage")],
)
async def cleanup_processes(
    request: Request,
    body: CleanupProcessesRequest,
    svc: ProcessManagerDependency,
) -> ManagedProcessCleanupResponse:
    """Delete completed or failed processes older than the cutoff."""
    removed = svc.cleanup_completed(
        tenant_id=_tenant_id(request),
        max_age_seconds=body.max_age_seconds,
    )
    return ManagedProcessCleanupResponse(removed=removed)


@router.get(
    "/{process_id}",
    response_model=ManagedProcessRecord,
    dependencies=[require_scope("processes:read")],
)
async def get_process(
    request: Request,
    process_id: str,
    svc: ProcessManagerDependency,
) -> ManagedProcessRecord:
    """Return one managed process."""
    try:
        return svc.get_process(process_id, tenant_id=_tenant_id(request))
    except ManagedProcessNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Process not found") from exc


@router.get(
    "/{process_id}/log",
    response_model=ManagedProcessLogResponse,
    dependencies=[require_scope("processes:read")],
)
async def get_process_log(
    request: Request,
    process_id: str,
    svc: ProcessManagerDependency,
    tail: int = 200,
) -> ManagedProcessLogResponse:
    """Return the tail of a managed process log."""
    try:
        content = svc.read_log(process_id, tenant_id=_tenant_id(request), tail=tail)
    except ManagedProcessNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Process not found") from exc
    line_count = 0 if not content else len(content.splitlines())
    return ManagedProcessLogResponse(
        process_id=process_id,
        content=content,
        line_count=line_count,
    )


@router.post(
    "/{process_id}/write",
    response_model=ManagedProcessRecord,
    dependencies=[require_scope("processes:manage")],
)
async def write_process_input(
    request: Request,
    process_id: str,
    body: WriteProcessInputRequest,
    svc: ProcessManagerDependency,
) -> ManagedProcessRecord:
    """Write stdin to a running process."""
    try:
        return await svc.write_stdin(process_id, body.data, tenant_id=_tenant_id(request))
    except ManagedProcessNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Process not found") from exc
    except ProcessValidationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete(
    "/{process_id}",
    response_model=ManagedProcessRecord,
    dependencies=[require_scope("processes:manage")],
)
async def terminate_process(
    request: Request,
    process_id: str,
    svc: ProcessManagerDependency,
) -> ManagedProcessRecord:
    """Terminate a managed process."""
    try:
        return await svc.terminate(process_id, tenant_id=_tenant_id(request))
    except ManagedProcessNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Process not found") from exc
