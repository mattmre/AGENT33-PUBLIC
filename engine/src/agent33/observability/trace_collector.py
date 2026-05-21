"""Trace collection service.

Creates, updates, and queries :class:`TraceRecord` and :class:`FailureRecord`
instances. In-memory storage (same pattern as the review service).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import ValidationError

from agent33.observability.failure import FailureCategory, FailureRecord, FailureSeverity
from agent33.observability.trace_models import (
    ActionStatus,
    TraceAction,
    TraceContext,
    TraceRecord,
    TraceStatus,
    TraceStep,
)

if TYPE_CHECKING:
    from agent33.services.orchestration_state import OrchestrationStateStore

logger = logging.getLogger(__name__)


class TraceNotFoundError(Exception):
    """Raised when a trace record is not found."""


class TraceCollector:
    """In-memory trace and failure collection service."""

    def __init__(self, state_store: OrchestrationStateStore | None = None) -> None:
        self._state_store = state_store
        self._traces: dict[str, TraceRecord] = {}
        self._failures: dict[str, FailureRecord] = {}
        self._load_state()

    def _persist_state(self) -> None:
        if self._state_store is None:
            return
        self._state_store.write_namespace(
            "traces",
            {
                "traces": {
                    trace_id: trace.model_dump(mode="json")
                    for trace_id, trace in self._traces.items()
                },
                "failures": {
                    failure_id: failure.model_dump(mode="json")
                    for failure_id, failure in self._failures.items()
                },
            },
        )

    def _load_state(self) -> None:
        if self._state_store is None:
            return
        payload = self._state_store.read_namespace("traces")

        traces_payload = payload.get("traces", {})
        if isinstance(traces_payload, dict):
            for trace_id, trace_data in traces_payload.items():
                if not isinstance(trace_id, str):
                    continue
                try:
                    self._traces[trace_id] = TraceRecord.model_validate(trace_data)
                except ValidationError:
                    logger.warning("trace_restore_failed id=%s", trace_id)

        failures_payload = payload.get("failures", {})
        if isinstance(failures_payload, dict):
            for failure_id, failure_data in failures_payload.items():
                if not isinstance(failure_id, str):
                    continue
                try:
                    self._failures[failure_id] = FailureRecord.model_validate(failure_data)
                except ValidationError:
                    logger.warning("trace_failure_restore_failed id=%s", failure_id)

    # ------------------------------------------------------------------
    # Trace CRUD
    # ------------------------------------------------------------------

    def start_trace(
        self,
        task_id: str = "",
        session_id: str = "",
        run_id: str = "",
        tenant_id: str = "",
        agent_id: str = "",
        agent_role: str = "",
        model: str = "",
    ) -> TraceRecord:
        """Create a new trace in RUNNING state."""
        trace = TraceRecord(
            task_id=task_id,
            session_id=session_id,
            run_id=run_id,
            tenant_id=tenant_id,
            context=TraceContext(
                agent_id=agent_id,
                agent_role=agent_role,
                model=model,
            ),
        )
        self._traces[trace.trace_id] = trace
        self._persist_state()
        logger.info("trace_started id=%s task=%s agent=%s", trace.trace_id, task_id, agent_id)
        return trace

    def get_trace(self, trace_id: str) -> TraceRecord:
        """Get a trace by ID."""
        trace = self._traces.get(trace_id)
        if trace is None:
            raise TraceNotFoundError(f"Trace not found: {trace_id}")
        return trace

    def get_trace_for_tenant(
        self,
        trace_id: str,
        *,
        tenant_id: str | None = None,
    ) -> TraceRecord:
        """Get a trace by ID, optionally enforcing tenant ownership."""
        trace = self.get_trace(trace_id)
        if tenant_id is not None and trace.tenant_id != tenant_id:
            raise TraceNotFoundError(f"Trace not found: {trace_id}")
        return trace

    def _trace_matches_tenant(self, trace_id: str, tenant_id: str) -> bool:
        trace = self._traces.get(trace_id)
        return trace is not None and trace.tenant_id == tenant_id

    def list_traces(
        self,
        tenant_id: str | None = None,
        status: TraceStatus | None = None,
        task_id: str | None = None,
        limit: int = 100,
    ) -> list[TraceRecord]:
        """List traces with optional filters."""
        results = list(self._traces.values())
        if tenant_id is not None:
            results = [t for t in results if t.tenant_id == tenant_id]
        if status is not None:
            results = [t for t in results if t.outcome.status == status]
        if task_id is not None:
            results = [t for t in results if t.task_id == task_id]
        # Most recent first
        results.sort(key=lambda t: t.started_at, reverse=True)
        return results[:limit]

    # ------------------------------------------------------------------
    # Trace lifecycle
    # ------------------------------------------------------------------

    def add_step(
        self,
        trace_id: str,
        step_id: str,
        *,
        tenant_id: str | None = None,
    ) -> TraceStep:
        """Add a new step to a trace."""
        trace = self.get_trace_for_tenant(trace_id, tenant_id=tenant_id)
        step = TraceStep(step_id=step_id, started_at=datetime.now(UTC))
        trace.execution.append(step)
        self._persist_state()
        return step

    def add_action(
        self,
        trace_id: str,
        step_id: str,
        action_id: str,
        tool: str,
        input_data: str = "",
        output_data: str = "",
        exit_code: int | None = None,
        duration_ms: int = 0,
        status: ActionStatus = ActionStatus.SUCCESS,
        tenant_id: str | None = None,
    ) -> TraceAction:
        """Add an action to a step within a trace."""
        trace = self.get_trace_for_tenant(trace_id, tenant_id=tenant_id)
        # Find the step
        step = next((s for s in trace.execution if s.step_id == step_id), None)
        if step is None:
            step = self.add_step(trace_id, step_id, tenant_id=tenant_id)

        action = TraceAction(
            action_id=action_id,
            tool=tool,
            input=input_data,
            output=output_data,
            exit_code=exit_code,
            duration_ms=duration_ms,
            status=status,
        )
        step.actions.append(action)
        self._persist_state()
        return action

    def complete_trace(
        self,
        trace_id: str,
        status: TraceStatus = TraceStatus.COMPLETED,
        failure_code: str = "",
        failure_message: str = "",
        tenant_id: str | None = None,
    ) -> TraceRecord:
        """Mark a trace as completed."""
        trace = self.get_trace_for_tenant(trace_id, tenant_id=tenant_id)
        trace.complete(status, failure_code, failure_message)

        # Complete any open steps
        for step in trace.execution:
            if step.completed_at is None:
                step.completed_at = trace.completed_at

        logger.info(
            "trace_completed id=%s status=%s duration_ms=%d",
            trace_id,
            status.value,
            trace.duration_ms,
        )
        self._persist_state()
        return trace

    # ------------------------------------------------------------------
    # Failure recording
    # ------------------------------------------------------------------

    def record_failure(
        self,
        trace_id: str,
        message: str,
        category: FailureCategory = FailureCategory.UNKNOWN,
        severity: FailureSeverity = FailureSeverity.MEDIUM,
        subcode: str = "",
        tenant_id: str | None = None,
    ) -> FailureRecord:
        """Record a failure against a trace."""
        trace = self.get_trace_for_tenant(trace_id, tenant_id=tenant_id)
        from agent33.observability.failure import _CATEGORY_META

        meta = _CATEGORY_META.get(category, {})
        failure = FailureRecord(
            trace_id=trace_id,
            classification={
                "code": category.value,
                "subcode": subcode,
                "category": category,
                "severity": severity,
            },
            message=message,
            resolution={
                "retryable": bool(meta.get("retryable", False)),
                "escalation_required": not meta.get("retryable", False),
            },
        )
        self._failures[failure.failure_id] = failure

        # Also update the trace outcome
        trace.outcome.failure_code = category.value
        trace.outcome.failure_message = message
        trace.outcome.failure_category = category.value

        logger.info(
            "failure_recorded id=%s trace=%s category=%s",
            failure.failure_id,
            trace_id,
            category.value,
        )
        self._persist_state()
        return failure

    def get_failure(self, failure_id: str) -> FailureRecord:
        """Get a failure record by ID."""
        failure = self._failures.get(failure_id)
        if failure is None:
            raise TraceNotFoundError(f"Failure not found: {failure_id}")
        return failure

    def list_failures(
        self,
        trace_id: str | None = None,
        category: FailureCategory | None = None,
        limit: int = 100,
        tenant_id: str | None = None,
    ) -> list[FailureRecord]:
        """List failure records with optional filters."""
        results = list(self._failures.values())
        if trace_id is not None:
            trace = self.get_trace_for_tenant(trace_id, tenant_id=tenant_id)
            results = [f for f in results if f.trace_id == trace.trace_id]
        elif tenant_id is not None:
            results = [f for f in results if self._trace_matches_tenant(f.trace_id, tenant_id)]
        if category is not None:
            results = [f for f in results if f.classification.category == category]
        results.sort(key=lambda f: f.occurred_at, reverse=True)
        return results[:limit]
