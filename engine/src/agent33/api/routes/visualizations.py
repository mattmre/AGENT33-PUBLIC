"""FastAPI router for workflow visualizations."""

from __future__ import annotations

import re
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request

from agent33.security.permissions import require_scope
from agent33.services.graph_generator import generate_workflow_graph
from agent33.workflows.dag import CycleDetectedError

logger = structlog.get_logger()

router = APIRouter(prefix="/v1/visualizations", tags=["visualizations"])
_WORKFLOW_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")


@router.get("/workflows/{workflow_id}/graph", dependencies=[require_scope("workflows:read")])
async def get_workflow_graph(
    workflow_id: str,
    request: Request,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Get visual graph representation of a workflow."""
    if not _WORKFLOW_ID_PATTERN.fullmatch(workflow_id):
        raise HTTPException(status_code=400, detail="Invalid workflow identifier format")

    # Import workflows route module to access route-level storage accessors.
    from agent33.api.routes import workflows

    workflow = workflows.get_workflow_registry().get(workflow_id)
    if workflow is None:
        raise HTTPException(
            status_code=404,
            detail=f"Workflow '{workflow_id}' not found",
        )

    execution_status: dict[str, str] = {}
    used_live_overlay = False
    if run_id:
        manager = getattr(request.app.state, "ws_manager", None)
        if manager is not None and await manager.has_run(run_id):
            user = _get_request_user(request)
            if not await manager.can_access_run(
                run_id,
                subject=user.sub,
                tenant_id=getattr(user, "tenant_id", ""),
                scopes=list(getattr(user, "scopes", [])),
            ):
                raise HTTPException(
                    status_code=404,
                    detail=f"Workflow run '{run_id}' not found",
                )
            live_event = await manager.build_sync_event(run_id)
            if live_event is not None and live_event.workflow_name == workflow_id:
                execution_status = dict(live_event.data.get("step_statuses", {}))
                used_live_overlay = True

    if not used_live_overlay:
        execution_history = workflows.get_execution_history()
        tenant_id, scopes = workflows.get_request_tenant_context(request)
        target_entry: dict[str, Any] | None = None
        recent_executions: list[dict[str, Any]] = []
        if execution_history:
            recent_executions = [
                entry
                for entry in execution_history
                if entry["workflow_name"] == workflow_id
                and workflows.execution_history_entry_visible(
                    entry,
                    requester_tenant_id=tenant_id,
                    requester_scopes=scopes,
                )
            ]
            if run_id:
                target_entry = next(
                    (
                        entry
                        for entry in recent_executions
                        if str(entry.get("run_id", "")).strip() == run_id
                    ),
                    None,
                )
            elif recent_executions:
                target_entry = max(
                    recent_executions,
                    key=lambda entry: entry.get("timestamp") or 0,
                )

        if target_entry is None and run_id:
            archive_service = workflows.get_workflow_run_archive_service()
            archived = archive_service.get_run(run_id) if archive_service is not None else None
            if isinstance(archived, dict):
                run_payload = archived.get("run", {})
                history_payload = archived.get("history", {})
                if (
                    isinstance(run_payload, dict)
                    and str(run_payload.get("workflow_name", "")).strip() == workflow_id
                    and workflows.tenant_access_allowed(
                        str(run_payload.get("tenant_id", "")),
                        requester_tenant_id=tenant_id,
                        requester_scopes=scopes,
                    )
                    and isinstance(history_payload, dict)
                ):
                    target_entry = history_payload
        if target_entry is None and recent_executions:
            target_entry = max(recent_executions, key=lambda entry: entry.get("timestamp") or 0)

        if target_entry is not None:
            step_statuses = target_entry.get("step_statuses")
            if step_statuses:
                execution_status = step_statuses
            else:
                workflow_status = target_entry.get("status")
                if workflow_status == "success":
                    for step in workflow.steps:
                        execution_status[step.id] = "success"
                elif workflow_status == "failed":
                    for step in workflow.steps:
                        execution_status[step.id] = "failed"

    try:
        graph = generate_workflow_graph(workflow, execution_status)
    except CycleDetectedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    logger.info(
        "workflow_graph_generated",
        workflow_id=workflow_id,
        run_id=run_id,
        node_count=len(graph.get("nodes", [])),
        edge_count=len(graph.get("edges", [])),
        has_status_overlay=bool(execution_status),
        used_live_overlay=used_live_overlay,
    )

    return graph


def _get_request_user(request: Request) -> Any:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
