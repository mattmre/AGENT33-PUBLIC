"""FastAPI router for workflow management and execution."""

from __future__ import annotations

import time
import uuid
from collections import deque
from typing import TYPE_CHECKING, Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from agent33.api.route_approvals import require_route_mutation_approval
from agent33.automation.scheduler import WorkflowScheduler
from agent33.security.injection import scan_inputs_recursive
from agent33.security.permissions import check_permission, require_scope
from agent33.tools.approvals import ApprovalRiskTier
from agent33.workflows.dag_layout import compute_dag_layout
from agent33.workflows.definition import WorkflowDefinition
from agent33.workflows.executor import WorkflowExecutor, WorkflowResult
from agent33.workflows.history import WorkflowExecutionRecord, normalize_execution_record

if TYPE_CHECKING:
    from agent33.workflows.run_archive import WorkflowRunArchiveService
    from agent33.workflows.state import WorkflowStateService

logger = structlog.get_logger()

router = APIRouter(prefix="/v1/workflows", tags=["workflows"])

# In-memory workflow registry
_registry: dict[str, WorkflowDefinition] = {}

# In-memory execution history (tenant ownership retained per run entry)
_MAX_EXECUTION_HISTORY = 1000
_execution_history: deque[dict[str, Any]] = deque(maxlen=_MAX_EXECUTION_HISTORY)

# Workflow scheduler instance
_scheduler: WorkflowScheduler | None = None
_ws_manager: Any | None = None
_workflow_state_service: WorkflowStateService | None = None
_workflow_run_archive_service: WorkflowRunArchiveService | None = None


def get_workflow_registry() -> dict[str, WorkflowDefinition]:
    """Expose the workflow registry for internal route composition."""
    if _workflow_state_service is not None:
        return _workflow_state_service.registry
    return _registry


def get_execution_history() -> deque[dict[str, Any]]:
    """Expose workflow execution history for internal route composition."""
    if _workflow_state_service is not None:
        return _workflow_state_service.execution_history
    return _execution_history


def set_workflow_state_service(service: WorkflowStateService | None) -> None:
    """Register the shared workflow state service for route access."""
    global _workflow_state_service
    _workflow_state_service = service


def get_workflow_run_archive_service() -> WorkflowRunArchiveService | None:
    """Expose the shared workflow run archive service for route composition."""
    return _workflow_run_archive_service


def set_workflow_run_archive_service(service: WorkflowRunArchiveService | None) -> None:
    """Register the shared workflow run archive service for route access."""
    global _workflow_run_archive_service
    _workflow_run_archive_service = service


def reset_workflow_state() -> None:
    """Clear workflow definitions and execution history."""
    if _workflow_state_service is not None:
        _workflow_state_service.clear()
        return
    _registry.clear()
    _execution_history.clear()


def _persist_workflow_state() -> None:
    if _workflow_state_service is not None:
        _workflow_state_service.persist_state()


def set_ws_manager(manager: Any | None) -> None:
    """Register the shared workflow WS manager for non-request code paths."""
    global _ws_manager
    _ws_manager = manager


def _start_workflow_run_archive(
    *,
    run_id: str,
    workflow_name: str,
    trigger_type: str,
    requested_inputs: dict[str, Any],
    owner_subject: str | None,
    tenant_id: str,
    job_id: str | None = None,
) -> None:
    archive_service = get_workflow_run_archive_service()
    if archive_service is None:
        return
    archive_service.start_run(
        run_id,
        workflow_name,
        trigger_type=trigger_type,
        owner_subject=owner_subject,
        tenant_id=tenant_id,
        metadata={
            "requested_inputs": requested_inputs,
            "job_id": job_id,
        },
    )


def _record_workflow_run_archive(
    *,
    run_id: str,
    history_record: WorkflowExecutionRecord,
    result_payload: dict[str, Any] | None,
) -> None:
    archive_service = get_workflow_run_archive_service()
    if archive_service is None:
        return
    archive_service.record_result(
        run_id,
        result_payload or {},
        history_record=history_record.model_dump(mode="json"),
    )


class WorkflowCreateRequest(BaseModel):
    """Request body for creating a workflow."""

    name: str
    version: str
    description: str | None = None
    triggers: dict[str, Any] = Field(default_factory=dict)
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    steps: list[dict[str, Any]]
    execution: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowExecuteRequest(BaseModel):
    """Request body for executing a workflow."""

    inputs: dict[str, Any] = Field(default_factory=dict)
    run_id: str | None = Field(default=None, min_length=1)
    dry_run: bool = False
    # Repeat/autonomous execution controls (safe defaults)
    repeat_count: int | None = Field(default=None, ge=1, le=100)
    repeat_interval_seconds: int | None = Field(default=None, ge=0, le=3600)
    autonomous: bool = False  # If True, returns execution metadata instead of result


class WorkflowSummary(BaseModel):
    """Summary of a registered workflow."""

    name: str
    version: str
    description: str | None = None
    step_count: int
    triggers: dict[str, Any] = Field(default_factory=dict)


class WorkflowScheduleRequest(BaseModel):
    """Request body for scheduling a workflow."""

    cron_expr: str | None = None  # Cron expression (5-field format)
    interval_seconds: int | None = Field(default=None, ge=1, le=86_400)
    inputs: dict[str, Any] = Field(default_factory=dict)  # Optional workflow inputs


class WorkflowScheduleResponse(BaseModel):
    """Response for scheduled workflow."""

    job_id: str
    workflow_name: str
    schedule_type: str
    schedule_expr: str
    inputs: dict[str, Any]


class WorkflowHistoryEntry(BaseModel):
    """Entry in workflow execution history."""

    run_id: str
    workflow_name: str
    trigger_type: str  # "manual" or "scheduled"
    status: str
    duration_ms: float
    timestamp: float
    error: str | None = None
    job_id: str | None = None  # Present for scheduled executions
    step_statuses: dict[str, str] | None = None  # Optional step-level status map


class WorkflowArchivedArtifact(BaseModel):
    """Persisted artifact metadata for one workflow run."""

    name: str
    relative_path: str
    size_bytes: int
    mime_type: str
    source: str
    step_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    preview: str = ""


class WorkflowArchivedRun(BaseModel):
    """Archived workflow run detail payload."""

    run: dict[str, Any]
    history: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[WorkflowArchivedArtifact] = Field(default_factory=list)


def get_request_tenant_context(request: Request) -> tuple[str, list[str]]:
    """Return the current request tenant and scopes."""
    user = getattr(request.state, "user", None)
    if user is None:
        return "", []
    return getattr(user, "tenant_id", ""), list(getattr(user, "scopes", []))


def tenant_access_allowed(
    owner_tenant_id: str,
    *,
    requester_tenant_id: str,
    requester_scopes: list[str],
) -> bool:
    """Return ``True`` when the caller may access a tenant-owned workflow run."""
    if check_permission("admin", requester_scopes):
        return True
    return owner_tenant_id == requester_tenant_id


def execution_history_entry_visible(
    entry: dict[str, Any],
    *,
    requester_tenant_id: str,
    requester_scopes: list[str],
) -> bool:
    """Return ``True`` when a history entry is visible to the current caller."""
    return tenant_access_allowed(
        str(entry.get("tenant_id", "")),
        requester_tenant_id=requester_tenant_id,
        requester_scopes=requester_scopes,
    )


def _get_archived_run_detail(run_id: str) -> dict[str, Any] | None:
    archive_service = get_workflow_run_archive_service()
    if archive_service is None:
        return None
    try:
        return archive_service.get_run(run_id)
    except ValueError:
        return None


def _assert_archived_run_access(run_id: str, request: Request) -> dict[str, Any]:
    archived = _get_archived_run_detail(run_id)
    if archived is None:
        raise HTTPException(status_code=404, detail=f"Workflow run '{run_id}' not found")
    run_payload = archived.get("run", {})
    if not isinstance(run_payload, dict):
        raise HTTPException(status_code=404, detail=f"Workflow run '{run_id}' not found")
    tenant_id, scopes = get_request_tenant_context(request)
    if not tenant_access_allowed(
        str(run_payload.get("tenant_id", "")),
        requester_tenant_id=tenant_id,
        requester_scopes=scopes,
    ):
        raise HTTPException(status_code=404, detail=f"Workflow run '{run_id}' not found")
    return archived


@router.get("/", dependencies=[require_scope("workflows:read")])
async def list_workflows() -> list[WorkflowSummary]:
    """List all registered workflows."""
    return [
        WorkflowSummary(
            name=w.name,
            version=w.version,
            description=w.description,
            step_count=len(w.steps),
            triggers=w.triggers.model_dump(),
        )
        for w in get_workflow_registry().values()
    ]


# -- Scheduling endpoints (must be before /{name} to avoid route conflicts) ----


@router.get("/schedules", dependencies=[require_scope("workflows:read")])
async def list_schedules() -> list[WorkflowScheduleResponse]:
    """List all scheduled workflow jobs."""
    if _scheduler is None:
        return []
    jobs = _scheduler.list_jobs()

    return [
        WorkflowScheduleResponse(
            job_id=job.job_id,
            workflow_name=job.workflow_name,
            schedule_type=job.schedule_type,
            schedule_expr=job.schedule_expr,
            inputs=job.inputs,
        )
        for job in jobs
    ]


@router.delete("/schedules/{job_id}", dependencies=[require_scope("workflows:execute")])
async def delete_schedule(job_id: str) -> dict[str, Any]:
    """Remove a scheduled workflow job."""
    removed = False
    if _scheduler is not None:
        removed = _scheduler.remove(job_id)

    if not removed:
        raise HTTPException(status_code=404, detail=f"Schedule '{job_id}' not found")

    logger.info("workflow_schedule_removed", job_id=job_id)

    return {"job_id": job_id, "removed": True}


# -- DAG visualization endpoints (must be before /{name} catch-all) ------------


@router.get("/runs/{run_id}/dag", dependencies=[require_scope("workflows:read")])
async def get_run_dag(run_id: str, req: Request) -> dict[str, Any]:
    """Return a positioned DAG layout with live run state overlay."""
    tenant_id, scopes = get_request_tenant_context(req)

    # Find the execution history entry for this run
    matched: tuple[dict[str, Any], WorkflowExecutionRecord] | None = None
    for entry in get_execution_history():
        record = normalize_execution_record(entry)
        if record.run_id != run_id:
            continue
        if not execution_history_entry_visible(
            entry,
            requester_tenant_id=tenant_id,
            requester_scopes=scopes,
        ):
            continue
        matched = (entry, record)
        break
    if matched is None:
        raise HTTPException(status_code=404, detail=f"Workflow run '{run_id}' not found")
    _entry, record = matched

    workflow_name = record.workflow_name
    workflow = get_workflow_registry().get(workflow_name)
    if workflow is None:
        raise HTTPException(
            status_code=404,
            detail=f"Workflow '{workflow_name}' no longer registered",
        )

    # Build run_state from step_statuses recorded in history
    run_state: dict[str, dict[str, Any]] = {}
    step_statuses = record.step_statuses or {}
    for step_id, status in step_statuses.items():
        run_state[step_id] = {"status": status}

    layout = compute_dag_layout(workflow, run_state=run_state)
    layout.run_id = run_id
    return layout.model_dump(mode="json")


@router.get("/runs/{run_id}", dependencies=[require_scope("workflows:read")])
async def get_archived_run(run_id: str, request: Request) -> WorkflowArchivedRun:
    """Return archived replay and artifact detail for one workflow run."""
    archived = _assert_archived_run_access(run_id, request)
    return WorkflowArchivedRun.model_validate(archived)


@router.get("/runs/{run_id}/events", dependencies=[require_scope("workflows:read")])
async def list_archived_run_events(
    run_id: str,
    request: Request,
    offset: int = 0,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Return archived workflow events for one run."""
    _assert_archived_run_access(run_id, request)
    archive_service = get_workflow_run_archive_service()
    if archive_service is None:
        raise HTTPException(status_code=503, detail="Workflow run archive service not available")
    return archive_service.list_events(run_id, offset=offset, limit=limit)


@router.get("/runs/{run_id}/artifacts", dependencies=[require_scope("workflows:read")])
async def list_archived_run_artifacts(
    run_id: str,
    request: Request,
) -> list[WorkflowArchivedArtifact]:
    """Return archived artifact metadata for one workflow run."""
    _assert_archived_run_access(run_id, request)
    archive_service = get_workflow_run_archive_service()
    if archive_service is None:
        raise HTTPException(status_code=503, detail="Workflow run archive service not available")
    artifacts = archive_service.list_artifacts(run_id)
    return [WorkflowArchivedArtifact.model_validate(artifact) for artifact in artifacts]


@router.get(
    "/runs/{run_id}/artifacts/{artifact_path:path}",
    dependencies=[require_scope("workflows:read")],
)
async def get_archived_run_artifact(
    run_id: str,
    artifact_path: str,
    request: Request,
) -> dict[str, Any]:
    """Return one archived text artifact payload for a workflow run."""
    _assert_archived_run_access(run_id, request)
    archive_service = get_workflow_run_archive_service()
    if archive_service is None:
        raise HTTPException(status_code=503, detail="Workflow run archive service not available")
    content = archive_service.get_artifact(run_id, artifact_path)
    if content is None:
        raise HTTPException(
            status_code=404,
            detail=f"Artifact '{artifact_path}' not found for workflow run '{run_id}'",
        )
    return {
        "run_id": run_id,
        "artifact_path": artifact_path,
        "content": content,
    }


@router.post("/{run_id}/resume", dependencies=[require_scope("workflows:execute")])
async def resume_workflow_run(run_id: str, req: Request) -> dict[str, Any]:
    """Resume a previously archived workflow run from its latest checkpoint."""
    checkpoint_manager = getattr(req.app.state, "checkpoint_manager", None)
    if checkpoint_manager is None:
        raise HTTPException(status_code=503, detail="Checkpoint manager not available")

    checkpoint = await checkpoint_manager.load_checkpoint(run_id)
    if checkpoint is None:
        raise HTTPException(status_code=404, detail=f"No checkpoint found for run '{run_id}'")

    archived = _assert_archived_run_access(run_id, req)
    run_payload = archived.get("run", {})
    if not isinstance(run_payload, dict):
        raise HTTPException(status_code=404, detail=f"Workflow run '{run_id}' not found")

    workflow_name = str(run_payload.get("workflow_name", "")).strip()
    workflow = get_workflow_registry().get(workflow_name)
    if workflow is None:
        raise HTTPException(
            status_code=404,
            detail=f"Workflow '{workflow_name}' no longer registered",
        )

    metadata = run_payload.get("metadata", {})
    requested_inputs = metadata.get("requested_inputs", {}) if isinstance(metadata, dict) else {}
    inputs = requested_inputs if isinstance(requested_inputs, dict) else {}
    scan = scan_inputs_recursive(inputs)
    if not scan.is_safe:
        raise HTTPException(
            status_code=400,
            detail=f"Input rejected: {', '.join(scan.threats)}",
        )

    ws_manager = getattr(req.app.state, "ws_manager", _ws_manager)
    execution_replay = getattr(req.app.state, "execution_replay", None)
    owner_subject = run_payload.get("owner_subject")
    tenant_id = str(run_payload.get("tenant_id", ""))

    request = WorkflowExecuteRequest(inputs=inputs, run_id=run_id)
    response = await _execute_single(
        workflow,
        workflow_name,
        request,
        trigger_type="resume",
        ws_manager=ws_manager,
        run_id=run_id,
        owner_subject=str(owner_subject) if owner_subject is not None else None,
        tenant_id=tenant_id,
        execution_replay=execution_replay,
        checkpoint_manager=checkpoint_manager,
        allow_existing_run_id=True,
    )
    response["resumed_from_checkpoint"] = True
    return response


# -- Dynamic workflow routes (must be after static routes like /schedules) -----


@router.get("/{name}", dependencies=[require_scope("workflows:read")])
async def get_workflow(name: str) -> dict[str, Any]:
    """Get a workflow definition by name."""
    workflow = get_workflow_registry().get(name)
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow '{name}' not found")
    return workflow.model_dump()


@router.get("/{name}/dag", dependencies=[require_scope("workflows:read")])
async def get_workflow_dag(name: str) -> dict[str, Any]:
    """Return a positioned DAG layout for a workflow definition."""
    workflow = get_workflow_registry().get(name)
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow '{name}' not found")

    layout = compute_dag_layout(workflow)
    return layout.model_dump(mode="json")


@router.post("/", status_code=201, dependencies=[require_scope("workflows:write")])
async def create_workflow(body: WorkflowCreateRequest, request: Request) -> dict[str, Any]:
    """Register a new workflow definition."""
    require_route_mutation_approval(
        request,
        route_name="workflows.create",
        operation="create",
        arguments=body.model_dump(mode="json"),
        details="Workflow registration requires explicit operator approval.",
        risk_tier=ApprovalRiskTier.MEDIUM,
    )
    try:
        definition = WorkflowDefinition.model_validate(body.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    registry = get_workflow_registry()
    if definition.name in registry:
        raise HTTPException(
            status_code=409,
            detail=f"Workflow '{definition.name}' already exists",
        )

    registry[definition.name] = definition
    _persist_workflow_state()
    logger.info("workflow_created", name=definition.name, version=definition.version)

    return {
        "name": definition.name,
        "version": definition.version,
        "step_count": len(definition.steps),
        "created": True,
    }


@router.post("/{name}/schedule", dependencies=[require_scope("workflows:execute")])
async def schedule_workflow(
    name: str, request: WorkflowScheduleRequest
) -> WorkflowScheduleResponse:
    """Schedule a workflow to run on a cron expression or interval."""
    workflow = get_workflow_registry().get(name)
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow '{name}' not found")

    scan = scan_inputs_recursive(request.inputs)
    if not scan.is_safe:
        raise HTTPException(
            status_code=400,
            detail=f"Input rejected: {', '.join(scan.threats)}",
        )

    # Validate that exactly one schedule type is provided
    if request.cron_expr and request.interval_seconds:
        raise HTTPException(
            status_code=400,
            detail="Provide either cron_expr or interval_seconds, not both",
        )
    if not request.cron_expr and not request.interval_seconds:
        raise HTTPException(
            status_code=400,
            detail="Must provide either cron_expr or interval_seconds",
        )

    scheduler = _get_scheduler()

    try:
        if request.cron_expr:
            job_id = scheduler.schedule_cron(
                workflow_name=name,
                cron_expr=request.cron_expr,
                inputs=request.inputs,
            )
            schedule_type = "cron"
            schedule_expr = request.cron_expr
        else:
            job_id = scheduler.schedule_interval(
                workflow_name=name,
                seconds=request.interval_seconds or 0,
                inputs=request.inputs,
            )
            schedule_type = "interval"
            schedule_expr = f"{request.interval_seconds}s"
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "workflow_scheduled",
        workflow_name=name,
        job_id=job_id,
        schedule_type=schedule_type,
    )

    return WorkflowScheduleResponse(
        job_id=job_id,
        workflow_name=name,
        schedule_type=schedule_type,
        schedule_expr=schedule_expr,
        inputs=request.inputs,
    )


@router.get("/{name}/history", dependencies=[require_scope("workflows:read")])
async def get_workflow_history(name: str, req: Request) -> list[WorkflowHistoryEntry]:
    """Get execution history for a specific workflow."""
    tenant_id, scopes = get_request_tenant_context(req)
    history: list[WorkflowHistoryEntry] = []
    for entry in get_execution_history():
        record = normalize_execution_record(entry)
        if record.workflow_name != name:
            continue
        if not execution_history_entry_visible(
            entry,
            requester_tenant_id=tenant_id,
            requester_scopes=scopes,
        ):
            continue
        history.append(WorkflowHistoryEntry(**record.model_dump(mode="json")))

    # Return most recent first
    return sorted(history, key=lambda x: x.timestamp, reverse=True)


@router.post("/{name}/execute", dependencies=[require_scope("workflows:execute")])
async def execute_workflow(
    name: str,
    request: WorkflowExecuteRequest,
    req: Request,
) -> dict[str, Any]:
    """Execute a registered workflow."""
    workflow = get_workflow_registry().get(name)
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow '{name}' not found")

    # Scan inputs for prompt injection (recursive to catch nested payloads)
    scan = scan_inputs_recursive(request.inputs)
    if not scan.is_safe:
        raise HTTPException(
            status_code=400,
            detail=f"Input rejected: {', '.join(scan.threats)}",
        )

    ws_manager = getattr(req.app.state, "ws_manager", _ws_manager)
    execution_replay = getattr(req.app.state, "execution_replay", None)
    checkpoint_manager = getattr(req.app.state, "checkpoint_manager", None)
    user = getattr(req.state, "user", None)
    owner_subject = getattr(user, "sub", None)
    tenant_id = getattr(user, "tenant_id", "") if user is not None else ""

    if request.run_id and request.repeat_count and request.repeat_count > 1:
        raise HTTPException(
            status_code=400,
            detail="Caller-supplied run_id is only supported for single executions",
        )

    # Handle repeat/autonomous execution
    if request.repeat_count or request.autonomous:
        return await _execute_repeated_or_autonomous(
            workflow,
            name,
            request,
            ws_manager=ws_manager,
            requested_run_id=request.run_id,
            owner_subject=owner_subject,
            tenant_id=tenant_id,
        )

    # Standard single execution (backward compatible)
    return await _execute_single(
        workflow,
        name,
        request,
        trigger_type="manual",
        ws_manager=ws_manager,
        run_id=request.run_id,
        owner_subject=owner_subject,
        tenant_id=tenant_id,
        execution_replay=execution_replay,
        checkpoint_manager=checkpoint_manager,
    )


async def _execute_single(
    workflow: WorkflowDefinition,
    name: str,
    request: WorkflowExecuteRequest,
    trigger_type: str = "manual",
    job_id: str | None = None,
    ws_manager: Any | None = None,
    run_id: str | None = None,
    owner_subject: str | None = None,
    tenant_id: str = "",
    execution_replay: Any | None = None,
    checkpoint_manager: Any | None = None,
    allow_existing_run_id: bool = False,
) -> dict[str, Any]:
    """Execute a workflow once and return the result."""
    if run_id is None or not allow_existing_run_id:
        run_id = await _allocate_run_id(run_id, ws_manager=ws_manager)
    assert run_id is not None
    archive_service = get_workflow_run_archive_service()
    archive_already_exists = (
        allow_existing_run_id and archive_service is not None and archive_service.has_run(run_id)
    )
    if not archive_already_exists:
        _start_workflow_run_archive(
            run_id=run_id,
            workflow_name=name,
            trigger_type=trigger_type,
            requested_inputs=dict(request.inputs),
            owner_subject=owner_subject,
            tenant_id=tenant_id,
            job_id=job_id,
        )

    # Optionally override dry_run
    if request.dry_run:
        workflow = workflow.model_copy(
            update={"execution": workflow.execution.model_copy(update={"dry_run": True})}
        )

    event_sink = None
    if ws_manager is not None:
        await ws_manager.register_run(
            run_id,
            name,
            owner_subject=owner_subject,
            tenant_id=tenant_id,
        )
        event_sink = ws_manager.publish_event

    executor = WorkflowExecutor(
        workflow,
        tenant_id=tenant_id,
        run_id=run_id,
        event_sink=event_sink,
        replay=execution_replay,
        checkpoint_manager=checkpoint_manager,
    )
    start_ts = time.time()
    start_monotonic = time.monotonic()

    try:
        result: WorkflowResult = await executor.execute(request.inputs)
        error = next(
            (
                step_result.error
                for step_result in reversed(result.step_results)
                if step_result.error is not None
            ),
            None,
        )
    except Exception as exc:
        logger.error("workflow_execution_failed", name=name, error=str(exc))
        duration_ms = (time.monotonic() - start_monotonic) * 1000
        if ws_manager is not None:
            from agent33.workflows.events import WorkflowEvent, WorkflowEventType

            await ws_manager.publish_event(
                WorkflowEvent(
                    event_type=WorkflowEventType.WORKFLOW_FAILED,
                    run_id=run_id,
                    workflow_name=name,
                    data={
                        "status": "failed",
                        "duration_ms": duration_ms,
                        "error": str(exc),
                    },
                )
            )
        # Record failure in history
        failed_record = WorkflowExecutionRecord(
            run_id=run_id,
            workflow_name=name,
            trigger_type=trigger_type,
            status="failed",
            duration_ms=duration_ms,
            timestamp=start_ts,
            error=str(exc),
            job_id=job_id,
            step_statuses=None,
            tenant_id=tenant_id,
        )
        get_execution_history().append(failed_record.model_dump(mode="json"))
        _persist_workflow_state()
        _record_workflow_run_archive(
            run_id=run_id,
            history_record=failed_record,
            result_payload={
                "run_id": run_id,
                "workflow_name": name,
                "status": "failed",
                "duration_ms": round(duration_ms, 2),
                "error": str(exc),
                "steps_executed": [],
                "step_results": [],
                "outputs": {},
            },
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Extract step statuses from result
    step_statuses = {sr.step_id: sr.status for sr in result.step_results}

    # Record success in history
    success_record = WorkflowExecutionRecord(
        run_id=run_id,
        workflow_name=name,
        trigger_type=trigger_type,
        status=result.status.value,
        duration_ms=result.duration_ms,
        timestamp=start_ts,
        error=error,
        job_id=job_id,
        step_statuses=step_statuses,
        tenant_id=tenant_id,
    )
    get_execution_history().append(success_record.model_dump(mode="json"))
    _persist_workflow_state()

    logger.info(
        "workflow_executed",
        name=name,
        status=result.status.value,
        duration_ms=result.duration_ms,
        trigger_type=trigger_type,
    )

    response = result.model_dump()
    response["run_id"] = run_id
    response["workflow_name"] = name
    _record_workflow_run_archive(
        run_id=run_id,
        history_record=success_record,
        result_payload=response,
    )
    return response


async def _execute_repeated_or_autonomous(
    workflow: WorkflowDefinition,
    name: str,
    request: WorkflowExecuteRequest,
    ws_manager: Any | None = None,
    requested_run_id: str | None = None,
    owner_subject: str | None = None,
    tenant_id: str = "",
) -> dict[str, Any]:
    """Execute a workflow multiple times or autonomously."""
    import asyncio

    repeat_count = request.repeat_count or 1
    interval = request.repeat_interval_seconds or 0
    results = []

    for i in range(repeat_count):
        if i > 0 and interval > 0:
            await asyncio.sleep(interval)

        run_id = requested_run_id if i == 0 else None
        result_dict = await _execute_single(
            workflow,
            name,
            request,
            trigger_type="manual",
            ws_manager=ws_manager,
            run_id=run_id,
            owner_subject=owner_subject,
            tenant_id=tenant_id,
        )
        results.append(result_dict)

    run_ids = [r["run_id"] for r in results]

    # If autonomous mode, return execution metadata instead of full results
    if request.autonomous:
        return {
            "executions": repeat_count,
            "workflow_name": name,
            "status": "completed",
            "run_ids": run_ids,
            "results_summary": [
                {
                    "run_id": r["run_id"],
                    "status": r["status"],
                    "duration_ms": r["duration_ms"],
                    "steps_executed": len(r["steps_executed"]),
                }
                for r in results
            ],
        }

    # Otherwise return last result (backward compatible for repeat_count=1)
    if not results:
        return {}

    response = dict(results[-1])
    if len(run_ids) > 1:
        response["run_ids"] = run_ids
    return response


async def _allocate_run_id(run_id: str | None, *, ws_manager: Any | None = None) -> str:
    """Return a unique workflow run identifier, honoring caller-supplied values."""
    if run_id is not None:
        try:
            exists = await _run_id_exists(run_id, ws_manager=ws_manager)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if exists:
            raise HTTPException(
                status_code=409,
                detail=f"Workflow run '{run_id}' already exists",
            )
        return run_id

    candidate = uuid.uuid4().hex
    while await _run_id_exists(candidate, ws_manager=ws_manager):
        candidate = uuid.uuid4().hex
    return candidate


async def _run_id_exists(run_id: str, *, ws_manager: Any | None = None) -> bool:
    """Return ``True`` when *run_id* is already present in tracked workflow state."""
    for entry in get_execution_history():
        if normalize_execution_record(entry).run_id == run_id:
            return True
    archive_service = get_workflow_run_archive_service()
    if archive_service is not None and archive_service.has_run(run_id):
        return True
    return ws_manager is not None and await ws_manager.has_run(run_id)


# -- Scheduling support functions ---------------------------------------------


def _get_scheduler() -> WorkflowScheduler:
    """Get or create the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = WorkflowScheduler(on_trigger=_scheduled_execution_callback)
        _scheduler.start()
        logger.info("workflow_scheduler_initialized")
    return _scheduler


async def _scheduled_execution_callback(
    job_id: str,
    workflow_name: str,
    inputs: dict[str, Any],
) -> None:
    """Callback invoked when a scheduled job triggers."""
    logger.info("scheduled_workflow_triggered", workflow_name=workflow_name, job_id=job_id)
    workflow = get_workflow_registry().get(workflow_name)
    if workflow is None:
        logger.error("scheduled_workflow_not_found", workflow_name=workflow_name, job_id=job_id)
        return

    scan = scan_inputs_recursive(inputs)
    if not scan.is_safe:
        logger.warning(
            "scheduled_workflow_input_rejected",
            workflow_name=workflow_name,
            job_id=job_id,
            threats=scan.threats,
        )
        return

    request = WorkflowExecuteRequest(inputs=inputs)
    try:
        await _execute_single(
            workflow,
            workflow_name,
            request,
            trigger_type="scheduled",
            job_id=job_id,
            ws_manager=_ws_manager,
        )
    except Exception as exc:
        logger.error(
            "scheduled_workflow_execution_failed",
            workflow_name=workflow_name,
            job_id=job_id,
            error=str(exc),
        )
