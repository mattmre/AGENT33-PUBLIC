"""Operations hub aggregation and lifecycle controls."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from agent33.api.routes.autonomy import get_autonomy_service
from agent33.api.routes.improvements import get_improvement_service
from agent33.api.routes.traces import get_trace_collector
from agent33.api.routes.workflows import (
    get_execution_history,
    get_workflow_run_archive_service,
)
from agent33.autonomy.models import BudgetState
from agent33.autonomy.service import BudgetNotFoundError
from agent33.improvement.models import IntakeStatus
from agent33.observability.trace_collector import TraceNotFoundError
from agent33.observability.trace_models import TraceStatus
from agent33.workflows.history import normalize_execution_record

logger = logging.getLogger(__name__)

_DEFAULT_INCLUDE = frozenset({"traces", "budgets", "improvements", "workflows"})
_MAX_LIMIT = 100
_WORKFLOW_ARCHIVE_EVENT_LIMIT = 200


class ProcessNotFoundError(Exception):
    """Raised when an operations process cannot be found."""


class UnsupportedControlError(Exception):
    """Raised when a lifecycle action is unsupported for a process type."""


class OperationsHubService:
    """Aggregate operations data and execute lifecycle controls."""

    def get_hub(
        self,
        *,
        tenant_id: str = "",
        include: set[str] | None = None,
        since: datetime | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Return normalized operations processes across subsystems."""
        now = datetime.now(UTC)
        since_dt = since or (now - timedelta(hours=24))
        include_set = include if include is not None else set(_DEFAULT_INCLUDE)
        capped_limit = max(1, min(limit, _MAX_LIMIT))

        processes: list[dict[str, Any]] = []
        if "traces" in include_set:
            processes.extend(
                self._trace_processes(
                    tenant_id=tenant_id,
                    since=since_dt,
                    status=status,
                    limit=capped_limit,
                )
            )
        if "budgets" in include_set and not tenant_id:
            processes.extend(
                self._budget_processes(
                    since=since_dt,
                    status=status,
                    limit=capped_limit,
                )
            )
        if "improvements" in include_set and not tenant_id:
            processes.extend(
                self._improvement_processes(since=since_dt, status=status, limit=capped_limit)
            )
        if "workflows" in include_set and not tenant_id:
            processes.extend(
                self._workflow_processes(
                    since=since_dt,
                    status=status,
                    limit=capped_limit,
                )
            )

        if status is not None:
            processes = [item for item in processes if item["status"] == status]

        processes.sort(key=lambda item: item["_started_at"], reverse=True)
        processes = processes[:capped_limit]
        for item in processes:
            item.pop("_started_at", None)

        return {
            "timestamp": now.isoformat(),
            "active_count": len(processes),
            "processes": processes,
        }

    def get_process(self, process_id: str, *, tenant_id: str = "") -> dict[str, Any]:
        """Return process detail for trace, budget, improvement, or workflow IDs."""
        if process_id.startswith("workflow:"):
            if tenant_id:
                raise ProcessNotFoundError(process_id)
            return self._workflow_detail(process_id)

        trace_collector = get_trace_collector()
        try:
            trace = trace_collector.get_trace(process_id)
            if tenant_id and trace.tenant_id != tenant_id:
                raise ProcessNotFoundError(process_id)
            return self._trace_detail(trace)
        except TraceNotFoundError as e:
            logger.warning("Missing %s during dashboard aggregation: %s", "trace", e)

        if not tenant_id:
            autonomy_service = get_autonomy_service()
            try:
                budget = autonomy_service.get_budget(process_id)
                return self._budget_detail(budget)
            except BudgetNotFoundError as e:
                logger.warning("Missing %s during dashboard aggregation: %s", "budget", e)

            improvement = get_improvement_service().get_intake(process_id)
            if improvement is not None:
                return self._improvement_detail(improvement)

        raise ProcessNotFoundError(process_id)

    def control_process(
        self, process_id: str, action: str, *, tenant_id: str = ""
    ) -> dict[str, Any]:
        """Control supported process lifecycles for traces and budgets."""
        trace_collector = get_trace_collector()
        try:
            trace = trace_collector.get_trace(process_id)
            if tenant_id and trace.tenant_id != tenant_id:
                raise ProcessNotFoundError(process_id)
            if action != "cancel":
                raise UnsupportedControlError(
                    f"Action '{action}' is unsupported for trace process"
                )
            trace_collector.complete_trace(
                process_id,
                status=TraceStatus.CANCELLED,
                failure_code="F-CAN",
                failure_message="Cancelled via operations hub",
            )
            return self.get_process(process_id, tenant_id=tenant_id)
        except TraceNotFoundError as e:
            logger.warning("Missing %s during dashboard aggregation: %s", "trace", e)

        if tenant_id:
            raise ProcessNotFoundError(process_id)

        autonomy_service = get_autonomy_service()
        try:
            _budget = autonomy_service.get_budget(process_id)
        except BudgetNotFoundError as exc:
            if process_id.startswith("workflow:"):
                raise UnsupportedControlError(
                    "Lifecycle control is not supported for workflow history records"
                ) from exc
            if get_improvement_service().get_intake(process_id) is not None:
                raise UnsupportedControlError(
                    "Lifecycle control is not supported for improvement intake records"
                ) from exc
            raise ProcessNotFoundError(process_id) from exc

        if action == "pause":
            autonomy_service.suspend(process_id)
        elif action == "resume":
            autonomy_service.activate(process_id)
        elif action == "cancel":
            # Prefer EXPIRED for cancellation semantics, fall back to COMPLETED if needed.
            try:
                autonomy_service.transition(process_id, BudgetState.EXPIRED)
            except Exception:
                autonomy_service.complete(process_id)
        else:
            raise UnsupportedControlError(f"Action '{action}' is unsupported for budget process")
        return self.get_process(process_id)

    def _trace_processes(
        self, *, tenant_id: str, since: datetime, status: str | None, limit: int
    ) -> list[dict[str, Any]]:
        collector = get_trace_collector()
        trace_status = TraceStatus.RUNNING if status is None else None
        traces = collector.list_traces(
            tenant_id=tenant_id or None,
            status=trace_status,
            limit=limit,
        )

        processes: list[dict[str, Any]] = []
        for trace in traces:
            if trace.started_at < since:
                continue
            processes.append(
                {
                    "id": trace.trace_id,
                    "type": "trace",
                    "status": trace.outcome.status.value,
                    "started_at": trace.started_at.isoformat(),
                    "name": trace.task_id or trace.trace_id,
                    "metadata": {
                        "tenant_id": trace.tenant_id,
                        "agent_id": trace.context.agent_id,
                        "session_id": trace.session_id,
                        "run_id": trace.run_id,
                    },
                    "_started_at": trace.started_at,
                }
            )
        return processes

    def _budget_processes(
        self, *, since: datetime, status: str | None, limit: int
    ) -> list[dict[str, Any]]:
        autonomy_service = get_autonomy_service()
        state_filter = BudgetState.ACTIVE if status is None else None
        budgets = autonomy_service.list_budgets(state=state_filter, limit=limit)

        processes: list[dict[str, Any]] = []
        for budget in budgets:
            if budget.created_at < since:
                continue
            processes.append(
                {
                    "id": budget.budget_id,
                    "type": "autonomy_budget",
                    "status": budget.state.value,
                    "started_at": budget.created_at.isoformat(),
                    "name": budget.task_id or budget.budget_id,
                    "metadata": {
                        "agent_id": budget.agent_id,
                    },
                    "_started_at": budget.created_at,
                }
            )
        return processes

    def _improvement_processes(
        self, *, since: datetime, status: str | None, limit: int
    ) -> list[dict[str, Any]]:
        service = get_improvement_service()
        intake_status = IntakeStatus.ANALYZING if status is None else None
        intakes = service.list_intakes(status=intake_status)

        processes: list[dict[str, Any]] = []
        for intake in intakes:
            if intake.submitted_at < since:
                continue
            processes.append(
                {
                    "id": intake.intake_id,
                    "type": "improvement_intake",
                    "status": intake.disposition.status.value,
                    "started_at": intake.submitted_at.isoformat(),
                    "name": intake.content.title,
                    "metadata": {
                        "research_type": intake.classification.research_type.value,
                        "urgency": intake.classification.urgency.value,
                    },
                    "_started_at": intake.submitted_at,
                }
            )
        processes.sort(key=lambda item: item["_started_at"], reverse=True)
        return processes[:limit]

    def _workflow_processes(
        self, *, since: datetime, status: str | None, limit: int
    ) -> list[dict[str, Any]]:
        history = list(get_execution_history())
        processes: list[dict[str, Any]] = []
        for entry in reversed(history):
            record = normalize_execution_record(entry)
            started_at = datetime.fromtimestamp(record.timestamp, UTC)
            if started_at < since:
                continue
            processes.append(
                {
                    "id": f"workflow:{record.run_id}",
                    "type": "workflow",
                    "status": record.status,
                    "started_at": started_at.isoformat(),
                    "name": record.workflow_name or "workflow",
                    "metadata": {
                        "run_id": record.run_id,
                        "trigger_type": record.trigger_type,
                        "duration_ms": record.duration_ms,
                        "error": record.error,
                        "job_id": record.job_id,
                    },
                    "_started_at": started_at,
                }
            )
            if len(processes) >= limit:
                break
        return processes

    def _trace_detail(self, trace: Any) -> dict[str, Any]:
        return {
            "id": trace.trace_id,
            "type": "trace",
            "status": trace.outcome.status.value,
            "started_at": trace.started_at.isoformat(),
            "name": trace.task_id or trace.trace_id,
            "metadata": {
                "tenant_id": trace.tenant_id,
                "agent_id": trace.context.agent_id,
                "session_id": trace.session_id,
                "run_id": trace.run_id,
            },
            "actions": [
                {
                    "step_id": step.step_id,
                    "action_count": len(step.actions),
                    "completed_at": step.completed_at.isoformat() if step.completed_at else None,
                }
                for step in trace.execution
            ],
        }

    def _budget_detail(self, budget: Any) -> dict[str, Any]:
        return {
            "id": budget.budget_id,
            "type": "autonomy_budget",
            "status": budget.state.value,
            "started_at": budget.created_at.isoformat(),
            "name": budget.task_id or budget.budget_id,
            "metadata": {
                "agent_id": budget.agent_id,
                "approved_by": budget.approved_by,
            },
        }

    def _improvement_detail(self, intake: Any) -> dict[str, Any]:
        return {
            "id": intake.intake_id,
            "type": "improvement_intake",
            "status": intake.disposition.status.value,
            "started_at": intake.submitted_at.isoformat(),
            "name": intake.content.title,
            "metadata": {
                "research_type": intake.classification.research_type.value,
                "urgency": intake.classification.urgency.value,
            },
        }

    def _workflow_detail(self, process_id: str) -> dict[str, Any]:
        if not process_id.startswith("workflow:"):
            raise ProcessNotFoundError(process_id)

        workflow_ref = process_id.split(":", 1)[1]
        legacy_parts = process_id.split(":", 2)
        legacy_workflow_name = legacy_parts[1] if len(legacy_parts) == 3 else ""
        legacy_target_ts = None
        if len(legacy_parts) == 3:
            try:
                legacy_target_ts = int(legacy_parts[2])
            except ValueError:
                raise ProcessNotFoundError(process_id) from None

        for entry in get_execution_history():
            record = normalize_execution_record(entry)
            timestamp = int(record.timestamp)
            if record.run_id == workflow_ref or (
                legacy_target_ts is not None
                and record.workflow_name == legacy_workflow_name
                and timestamp == legacy_target_ts
            ):
                started_at = datetime.fromtimestamp(record.timestamp, UTC)
                archive_service = get_workflow_run_archive_service()
                archive_detail = (
                    archive_service.get_run(record.run_id)
                    if archive_service is not None and hasattr(archive_service, "get_run")
                    else None
                )
                archive_events = (
                    archive_service.list_events(
                        record.run_id,
                        offset=0,
                        limit=_WORKFLOW_ARCHIVE_EVENT_LIMIT,
                    )
                    if archive_service is not None and hasattr(archive_service, "list_events")
                    else []
                )
                archive_artifacts = (
                    archive_service.list_artifacts(record.run_id)
                    if archive_service is not None and hasattr(archive_service, "list_artifacts")
                    else []
                )
                metadata = {
                    "run_id": record.run_id,
                    "trigger_type": record.trigger_type,
                    "duration_ms": record.duration_ms,
                    "error": record.error,
                    "job_id": record.job_id,
                }
                if isinstance(archive_detail, dict):
                    run_payload = archive_detail.get("run", {})
                    if isinstance(run_payload, dict):
                        if run_payload.get("event_count") is not None:
                            metadata["event_count"] = run_payload["event_count"]
                        if run_payload.get("artifact_count") is not None:
                            metadata["artifact_count"] = run_payload["artifact_count"]
                        if run_payload.get("owner_subject") is not None:
                            metadata["owner_subject"] = run_payload["owner_subject"]
                        archive_metadata = run_payload.get("metadata")
                        if isinstance(archive_metadata, dict):
                            if archive_metadata.get("requested_inputs") is not None:
                                metadata["requested_inputs"] = archive_metadata["requested_inputs"]
                            if archive_metadata.get("job_id") is not None:
                                metadata["job_id"] = archive_metadata["job_id"]
                    if archive_events:
                        metadata["first_event_at"] = archive_events[0].get("timestamp")
                        metadata["last_event_at"] = archive_events[-1].get("timestamp")
                    if archive_detail.get("result") is not None:
                        metadata["result_payload"] = archive_detail["result"]
                if archive_artifacts:
                    metadata["artifact_count"] = len(archive_artifacts)
                    metadata["artifacts"] = archive_artifacts
                return {
                    "id": f"workflow:{record.run_id}",
                    "type": "workflow",
                    "status": record.status,
                    "started_at": started_at.isoformat(),
                    "name": record.workflow_name or "workflow",
                    "metadata": metadata,
                    "actions": _workflow_archive_actions(archive_events),
                }
        raise ProcessNotFoundError(process_id)


def _workflow_archive_actions(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for event in events:
        step_id = str(event.get("step_id", "")).strip()
        if not step_id:
            continue
        action = grouped.setdefault(
            step_id,
            {
                "step_id": step_id,
                "action_count": 0,
                "completed_at": None,
            },
        )
        action["action_count"] = int(action["action_count"]) + 1
        event_type = str(event.get("type", ""))
        if event_type in {"step_completed", "step_failed", "step_skipped"}:
            action["completed_at"] = _event_iso_timestamp(event.get("timestamp"))

    def _sort_key(value: dict[str, Any]) -> tuple[int, str]:
        completed_at = value.get("completed_at")
        return (0 if completed_at else 1, str(completed_at or value.get("step_id", "")))

    return sorted(grouped.values(), key=_sort_key)


def _event_iso_timestamp(value: Any) -> str | None:
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(timestamp, UTC).isoformat()
