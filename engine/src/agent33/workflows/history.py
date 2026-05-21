"""Canonical workflow run-history normalization helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from collections.abc import Mapping


class WorkflowExecutionRecord(BaseModel):
    """Canonical execution history record for workflow runs."""

    run_id: str = Field(min_length=1)
    workflow_name: str
    trigger_type: str
    status: str
    duration_ms: float
    timestamp: float
    error: str | None = None
    job_id: str | None = None
    step_statuses: dict[str, str] | None = None
    tenant_id: str = ""


def legacy_run_id(workflow_name: str, timestamp: float) -> str:
    """Generate a stable compatibility run identifier for legacy history blobs."""
    normalized_name = workflow_name.strip() or "workflow"
    return f"legacy-{normalized_name}-{int(timestamp * 1000)}"


def normalize_execution_record(
    entry: Mapping[str, Any] | WorkflowExecutionRecord,
) -> WorkflowExecutionRecord:
    """Return a canonical execution record with a guaranteed ``run_id``."""
    if isinstance(entry, WorkflowExecutionRecord):
        return entry

    payload = dict(entry)
    workflow_name = str(payload.get("workflow_name", "")).strip()
    timestamp = _coerce_float(payload.get("timestamp", 0.0))
    step_statuses = payload.get("step_statuses")
    normalized_step_statuses = (
        {str(step_id): str(status) for step_id, status in step_statuses.items()}
        if isinstance(step_statuses, dict)
        else None
    )

    return WorkflowExecutionRecord.model_validate(
        {
            "run_id": str(payload.get("run_id", "")).strip()
            or legacy_run_id(workflow_name, timestamp),
            "workflow_name": workflow_name,
            "trigger_type": str(payload.get("trigger_type", "manual")),
            "status": str(payload.get("status", "unknown")),
            "duration_ms": _coerce_float(payload.get("duration_ms", 0.0)),
            "timestamp": timestamp,
            "error": _coerce_optional_str(payload.get("error")),
            "job_id": _coerce_optional_str(payload.get("job_id")),
            "step_statuses": normalized_step_statuses,
            "tenant_id": str(payload.get("tenant_id", "")),
        }
    )


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _coerce_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value)
    return normalized if normalized else None
