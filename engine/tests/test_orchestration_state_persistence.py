"""Durable shared-state persistence tests for orchestration services."""

from __future__ import annotations

from agent33.autonomy.service import AutonomyService
from agent33.observability.trace_collector import TraceCollector
from agent33.observability.trace_models import TraceStatus
from agent33.release.models import SyncRule
from agent33.release.service import ReleaseService
from agent33.services.orchestration_state import OrchestrationStateStore
from agent33.workflows.definition import WorkflowDefinition
from agent33.workflows.state import WorkflowStateService


def _new_store(path: str) -> OrchestrationStateStore:
    return OrchestrationStateStore(path)


def test_autonomy_service_state_restores_after_restart(tmp_path) -> None:
    path = tmp_path / "orchestration_state.json"

    service = AutonomyService(state_store=_new_store(str(path)))
    budget = service.create_budget(task_id="task-restore", agent_id="agent-1")
    service.activate(budget.budget_id, approved_by="operator")
    service.create_enforcer(budget.budget_id)
    service.enforce_command(budget.budget_id, "echo hello")
    service.trigger_escalation(
        budget_id=budget.budget_id,
        description="needs operator review",
    )

    restored = AutonomyService(state_store=_new_store(str(path)))
    loaded_budget = restored.get_budget(budget.budget_id)
    assert loaded_budget.state.value == "active"
    assert restored.get_enforcer(budget.budget_id) is not None
    assert len(restored.list_escalations(budget_id=budget.budget_id)) == 1


def test_release_service_state_restores_after_restart(tmp_path) -> None:
    path = tmp_path / "orchestration_state.json"

    service = ReleaseService(state_store=_new_store(str(path)))
    release = service.create_release(version="1.2.3")
    service.freeze(release.release_id)
    rule = service.add_sync_rule(
        SyncRule(
            source_pattern="core/**/*.md",
            target_repo="org/repo",
        )
    )
    service.sync_engine.dry_run(rule.rule_id, ["core/orchestrator/RELEASE.md"])
    service.initiate_rollback(release.release_id, reason="verify persistence")

    restored = ReleaseService(state_store=_new_store(str(path)))
    loaded_release = restored.get_release(release.release_id)
    assert loaded_release.status.value == "frozen"
    assert len(restored.list_sync_rules()) == 1
    assert len(restored.sync_engine.list_executions()) == 1
    assert len(restored.rollback_manager.list_all(release_id=release.release_id)) == 1


def test_trace_collector_state_restores_after_restart(tmp_path) -> None:
    path = tmp_path / "orchestration_state.json"

    collector = TraceCollector(state_store=_new_store(str(path)))
    trace = collector.start_trace(task_id="trace-restore", agent_id="agent-9")
    collector.add_action(
        trace_id=trace.trace_id,
        step_id="step-1",
        action_id="action-1",
        tool="shell",
        input_data="echo hello",
        output_data="hello",
        duration_ms=10,
    )
    collector.record_failure(trace.trace_id, message="transient failure")
    collector.complete_trace(trace.trace_id, status=TraceStatus.FAILED)

    restored = TraceCollector(state_store=_new_store(str(path)))
    loaded_trace = restored.get_trace(trace.trace_id)
    assert loaded_trace.outcome.status == TraceStatus.FAILED
    failures = restored.list_failures(trace_id=trace.trace_id)
    assert len(failures) == 1


def test_workflow_state_restores_after_restart(tmp_path) -> None:
    path = tmp_path / "orchestration_state.json"

    service = WorkflowStateService(state_store=_new_store(str(path)), max_execution_history=5)
    definition = WorkflowDefinition.model_validate(
        {
            "name": "restart-safe-workflow",
            "version": "1.0.0",
            "description": "Workflow persistence test",
            "steps": [
                {
                    "id": "step-1",
                    "action": "transform",
                    "transform": "inputs",
                }
            ],
            "execution": {"mode": "sequential"},
        }
    )
    service.registry[definition.name] = definition
    service.execution_history.append(
        {
            "run_id": "run-restart-safe",
            "workflow_name": definition.name,
            "trigger_type": "manual",
            "status": "success",
            "duration_ms": 12.5,
            "timestamp": 1234.5,
            "error": None,
            "job_id": None,
            "step_statuses": {"step-1": "success"},
            "tenant_id": "tenant-a",
        }
    )
    service.persist_state()

    restored = WorkflowStateService(state_store=_new_store(str(path)), max_execution_history=5)
    restored_definition = restored.registry.get(definition.name)
    assert restored_definition is not None
    assert restored_definition.description == "Workflow persistence test"
    assert len(restored.execution_history) == 1
    restored_entry = restored.execution_history[0]
    assert restored_entry["run_id"] == "run-restart-safe"
    assert restored_entry["workflow_name"] == definition.name
    assert restored_entry["tenant_id"] == "tenant-a"
