"""Sub-Agent Spawner API endpoints (Phase 71).

Provides CRUD for spawner workflow definitions and execution/status endpoints
that leverage the existing DelegationManager (Phase 53).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from agent33.security.permissions import require_scope
from agent33.spawner.models import (
    ChildAgentConfig,
    ExecutionTree,
    IsolationMode,
    SubAgentWorkflow,
)

if TYPE_CHECKING:
    from agent33.spawner.service import SpawnerService

router = APIRouter(prefix="/v1/spawner", tags=["spawner"])
logger = logging.getLogger(__name__)


# -- dependency helpers ---------------------------------------------------


def _get_spawner_service(request: Request) -> SpawnerService:
    """Resolve SpawnerService from app state or raise 503."""
    service: SpawnerService | None = getattr(request.app.state, "spawner_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="SpawnerService not initialized",
        )
    return service


# -- request / response models -------------------------------------------


class ChildAgentConfigBody(BaseModel):
    """Child agent config in API request bodies."""

    agent_name: str = Field(min_length=1)
    system_prompt_override: str | None = None
    tool_allowlist: list[str] = Field(default_factory=list)
    autonomy_level: int = Field(default=1, ge=0, le=3)
    isolation: IsolationMode = IsolationMode.LOCAL
    pack_names: list[str] = Field(default_factory=list)


class CreateWorkflowBody(BaseModel):
    """Body for POST /v1/spawner/workflows."""

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    parent_agent: str = Field(min_length=1)
    children: list[ChildAgentConfigBody] = Field(default_factory=list)


class WorkflowResponse(BaseModel):
    """Serialised workflow for API responses."""

    id: str
    name: str
    description: str
    parent_agent: str
    children: list[ChildAgentConfigBody]
    created_at: str
    updated_at: str


class ExecutionNodeResponse(BaseModel):
    """Serialised execution node."""

    agent_name: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    result_summary: str | None = None
    error: str | None = None
    children: list[ExecutionNodeResponse] = Field(default_factory=list)


class ExecutionTreeResponse(BaseModel):
    """Serialised execution tree for API responses."""

    workflow_id: str
    execution_id: str
    status: str
    root: ExecutionNodeResponse
    started_at: str | None = None
    completed_at: str | None = None


# -- serialisation helpers ------------------------------------------------


def _workflow_to_response(wf: SubAgentWorkflow) -> WorkflowResponse:
    return WorkflowResponse(
        id=wf.id,
        name=wf.name,
        description=wf.description,
        parent_agent=wf.parent_agent,
        children=[
            ChildAgentConfigBody(
                agent_name=c.agent_name,
                system_prompt_override=c.system_prompt_override,
                tool_allowlist=c.tool_allowlist,
                autonomy_level=c.autonomy_level,
                isolation=c.isolation,
                pack_names=c.pack_names,
            )
            for c in wf.children
        ],
        created_at=wf.created_at.isoformat(),
        updated_at=wf.updated_at.isoformat(),
    )


def _node_to_response(node: Any) -> ExecutionNodeResponse:
    return ExecutionNodeResponse(
        agent_name=node.agent_name,
        status=node.status,
        started_at=node.started_at.isoformat() if node.started_at else None,
        completed_at=node.completed_at.isoformat() if node.completed_at else None,
        result_summary=node.result_summary,
        error=node.error,
        children=[_node_to_response(c) for c in node.children],
    )


def _tree_to_response(tree: ExecutionTree) -> ExecutionTreeResponse:
    return ExecutionTreeResponse(
        workflow_id=tree.workflow_id,
        execution_id=tree.execution_id,
        status=tree.status,
        root=_node_to_response(tree.root),
        started_at=tree.started_at.isoformat() if tree.started_at else None,
        completed_at=tree.completed_at.isoformat() if tree.completed_at else None,
    )


# -- routes ---------------------------------------------------------------


@router.post(
    "/workflows",
    response_model=WorkflowResponse,
    status_code=201,
    dependencies=[require_scope("agents:write")],
)
async def create_workflow(
    body: CreateWorkflowBody,
    request: Request,
) -> WorkflowResponse:
    """Save a new sub-agent workflow definition."""
    service = _get_spawner_service(request)

    children = [
        ChildAgentConfig(
            agent_name=c.agent_name,
            system_prompt_override=c.system_prompt_override,
            tool_allowlist=c.tool_allowlist,
            autonomy_level=c.autonomy_level,
            isolation=c.isolation,
            pack_names=c.pack_names,
        )
        for c in body.children
    ]

    workflow = SubAgentWorkflow(
        name=body.name,
        description=body.description,
        parent_agent=body.parent_agent,
        children=children,
    )

    try:
        saved = service.create_workflow(workflow)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return _workflow_to_response(saved)


@router.get(
    "/workflows",
    response_model=list[WorkflowResponse],
    dependencies=[require_scope("agents:read")],
)
async def list_workflows(
    request: Request,
) -> list[WorkflowResponse]:
    """List all saved spawner workflow definitions."""
    service = _get_spawner_service(request)
    return [_workflow_to_response(wf) for wf in service.list_workflows()]


@router.get(
    "/workflows/{workflow_id}",
    response_model=WorkflowResponse,
    dependencies=[require_scope("agents:read")],
)
async def get_workflow(
    workflow_id: str,
    request: Request,
) -> WorkflowResponse:
    """Get a specific spawner workflow definition by ID."""
    service = _get_spawner_service(request)
    wf = service.get_workflow(workflow_id)
    if wf is None:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found")
    return _workflow_to_response(wf)


@router.delete(
    "/workflows/{workflow_id}",
    dependencies=[require_scope("agents:write")],
)
async def delete_workflow(
    workflow_id: str,
    request: Request,
) -> dict[str, Any]:
    """Delete a spawner workflow definition."""
    service = _get_spawner_service(request)
    deleted = service.delete_workflow(workflow_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found")
    return {"deleted": True, "workflow_id": workflow_id}


@router.post(
    "/workflows/{workflow_id}/execute",
    response_model=ExecutionTreeResponse,
    dependencies=[require_scope("agents:invoke")],
)
async def execute_workflow(
    workflow_id: str,
    request: Request,
) -> ExecutionTreeResponse:
    """Execute a spawner workflow, delegating to child agents."""
    service = _get_spawner_service(request)
    try:
        tree = service.execute_workflow(workflow_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _tree_to_response(tree)


@router.get(
    "/workflows/{workflow_id}/status",
    response_model=ExecutionTreeResponse,
    dependencies=[require_scope("agents:read")],
)
async def workflow_status(
    workflow_id: str,
    request: Request,
) -> ExecutionTreeResponse:
    """Get the latest execution tree status for a workflow."""
    service = _get_spawner_service(request)
    tree = service.get_latest_execution(workflow_id)
    if tree is None:
        raise HTTPException(
            status_code=404,
            detail=f"No executions found for workflow '{workflow_id}'",
        )
    return _tree_to_response(tree)
