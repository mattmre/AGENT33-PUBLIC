"""FastAPI router for trace and failure queries."""

# NOTE: no ``from __future__ import annotations`` — Pydantic needs these
# types at runtime for request-body validation.

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from agent33.api.routes.tenant_access import require_tenant_context, tenant_filter_for_request
from agent33.observability.failure import FailureCategory, FailureSeverity
from agent33.observability.trace_collector import TraceCollector, TraceNotFoundError
from agent33.observability.trace_models import ActionStatus, TraceStatus
from agent33.security.permissions import require_scope

logger = structlog.get_logger()

router = APIRouter(prefix="/v1/traces", tags=["traces"])

# Singleton collector (same pattern as reviews service)
_collector = TraceCollector()


def set_trace_collector(collector: TraceCollector) -> None:
    """Inject a shared trace collector instance (called from lifespan)."""
    global _collector  # noqa: PLW0603
    _collector = collector


def get_trace_collector() -> TraceCollector:
    """Return the trace collector singleton (for testing injection)."""
    return _collector


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class StartTraceRequest(BaseModel):
    task_id: str = ""
    session_id: str = ""
    run_id: str = ""
    agent_id: str = ""
    agent_role: str = ""
    model: str = ""


class AddActionRequest(BaseModel):
    step_id: str
    action_id: str
    tool: str
    input_data: str = ""
    output_data: str = ""
    exit_code: int | None = None
    duration_ms: int = 0
    status: ActionStatus = ActionStatus.SUCCESS


class CompleteTraceRequest(BaseModel):
    status: TraceStatus = TraceStatus.COMPLETED
    failure_code: str = ""
    failure_message: str = ""


class RecordFailureRequest(BaseModel):
    message: str
    category: FailureCategory = FailureCategory.UNKNOWN
    severity: FailureSeverity = FailureSeverity.MEDIUM
    subcode: str = ""


class TraceSummary(BaseModel):
    trace_id: str
    task_id: str
    agent_id: str
    status: str
    started_at: str
    duration_ms: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_tenant_id(request: Request) -> str:
    tenant_id, _ = require_tenant_context(request)
    return tenant_id


def _tenant_filter(request: Request) -> str | None:
    return tenant_filter_for_request(request)


# ---------------------------------------------------------------------------
# Trace routes
# ---------------------------------------------------------------------------


@router.post("/", status_code=201, dependencies=[require_scope("tools:execute")])
async def start_trace(body: StartTraceRequest, request: Request) -> dict[str, Any]:
    """Start a new trace."""
    tenant_id = _get_tenant_id(request)
    trace = _collector.start_trace(
        task_id=body.task_id,
        session_id=body.session_id,
        run_id=body.run_id,
        tenant_id=tenant_id,
        agent_id=body.agent_id,
        agent_role=body.agent_role,
        model=body.model,
    )
    return {"trace_id": trace.trace_id, "status": trace.outcome.status.value}


@router.get("/", dependencies=[require_scope("workflows:read")])
async def list_traces(
    request: Request,
    status: str | None = None,
    task_id: str | None = None,
    limit: int = 100,
) -> list[TraceSummary]:
    """List traces with optional filters."""
    status_filter = TraceStatus(status) if status else None
    traces = _collector.list_traces(
        tenant_id=_tenant_filter(request),
        status=status_filter,
        task_id=task_id,
        limit=limit,
    )
    return [
        TraceSummary(
            trace_id=t.trace_id,
            task_id=t.task_id,
            agent_id=t.context.agent_id,
            status=t.outcome.status.value,
            started_at=t.started_at.isoformat(),
            duration_ms=t.duration_ms,
        )
        for t in traces
    ]


@router.get("/{trace_id}", dependencies=[require_scope("workflows:read")])
async def get_trace(trace_id: str, request: Request) -> dict[str, Any]:
    """Get a trace record by ID."""
    try:
        trace = _collector.get_trace_for_tenant(trace_id, tenant_id=_tenant_filter(request))
    except TraceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return trace.model_dump(mode="json")


@router.post("/{trace_id}/actions", dependencies=[require_scope("tools:execute")])
async def add_action(trace_id: str, body: AddActionRequest, request: Request) -> dict[str, Any]:
    """Add an action to a trace step."""
    try:
        action = _collector.add_action(
            trace_id=trace_id,
            step_id=body.step_id,
            action_id=body.action_id,
            tool=body.tool,
            input_data=body.input_data,
            output_data=body.output_data,
            exit_code=body.exit_code,
            duration_ms=body.duration_ms,
            status=body.status,
            tenant_id=_tenant_filter(request),
        )
    except TraceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"action_id": action.action_id, "status": action.status.value}


@router.post("/{trace_id}/complete", dependencies=[require_scope("tools:execute")])
async def complete_trace(
    trace_id: str, body: CompleteTraceRequest, request: Request
) -> dict[str, Any]:
    """Mark a trace as completed."""
    try:
        trace = _collector.complete_trace(
            trace_id=trace_id,
            status=body.status,
            failure_code=body.failure_code,
            failure_message=body.failure_message,
            tenant_id=_tenant_filter(request),
        )
    except TraceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "trace_id": trace.trace_id,
        "status": trace.outcome.status.value,
        "duration_ms": trace.duration_ms,
    }


# ---------------------------------------------------------------------------
# Failure routes
# ---------------------------------------------------------------------------


@router.post(
    "/{trace_id}/failures",
    status_code=201,
    dependencies=[require_scope("tools:execute")],
)
async def record_failure(
    trace_id: str, body: RecordFailureRequest, request: Request
) -> dict[str, Any]:
    """Record a failure against a trace."""
    try:
        failure = _collector.record_failure(
            trace_id=trace_id,
            message=body.message,
            category=body.category,
            severity=body.severity,
            subcode=body.subcode,
            tenant_id=_tenant_filter(request),
        )
    except TraceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "failure_id": failure.failure_id,
        "category": failure.classification.category.value,
    }


@router.get(
    "/{trace_id}/failures",
    dependencies=[require_scope("workflows:read")],
)
async def list_failures(
    trace_id: str,
    request: Request,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """List failures for a trace."""
    cat_filter = FailureCategory(category) if category else None
    try:
        failures = _collector.list_failures(
            trace_id=trace_id,
            category=cat_filter,
            tenant_id=_tenant_filter(request),
        )
    except TraceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [f.model_dump(mode="json") for f in failures]
