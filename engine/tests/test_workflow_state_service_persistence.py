from __future__ import annotations

from collections import deque
from typing import Any

from agent33.services.orchestration_state import OrchestrationStateStore
from agent33.workflows.definition import WorkflowDefinition
from agent33.workflows.state import WorkflowStateService


def _workflow_definition(name: str = "restart-safe-workflow") -> WorkflowDefinition:
    return WorkflowDefinition.model_validate(
        {
            "name": name,
            "version": "1.0.0",
            "description": "Workflow persistence coverage",
            "steps": [
                {
                    "id": "step-a",
                    "action": "transform",
                    "transform": "inputs",
                }
            ],
            "execution": {"mode": "sequential"},
        }
    )


def test_workflow_state_restores_into_supplied_containers_after_restart(tmp_path) -> None:
    state_path = tmp_path / "workflow_state.json"
    state_store = OrchestrationStateStore(str(state_path))
    registry: dict[str, WorkflowDefinition] = {}
    history: deque[dict[str, Any]] = deque(maxlen=8)
    service = WorkflowStateService(
        state_store,
        registry=registry,
        execution_history=history,
    )

    definition = _workflow_definition()
    registry[definition.name] = definition
    history.append(
        {
            "workflow_name": definition.name,
            "trigger_type": "manual",
            "status": "success",
            "duration_ms": 12.5,
            "timestamp": 1_710_000_000.0,
            "step_statuses": {"step-a": "success"},
            "tenant_id": "tenant-a",
        }
    )
    service.persist_state()

    restored_registry: dict[str, WorkflowDefinition] = {}
    restored_history: deque[dict[str, Any]] = deque(maxlen=8)
    restarted = WorkflowStateService(
        OrchestrationStateStore(str(state_path)),
        registry=restored_registry,
        execution_history=restored_history,
    )

    assert restarted.registry is restored_registry
    assert restarted.execution_history is restored_history

    restored_definition = restarted.get_workflow(definition.name)
    assert restored_definition is not None
    assert restored_definition.version == "1.0.0"
    assert restored_definition.description == "Workflow persistence coverage"
    assert restored_definition.steps[0].id == "step-a"

    restored_records = restarted.list_execution_records(workflow_name=definition.name)
    assert len(restored_records) == 1
    assert restored_records[0].run_id.startswith(f"legacy-{definition.name}-")
    assert restored_records[0].tenant_id == "tenant-a"
    assert restored_records[0].step_statuses == {"step-a": "success"}
    assert restored_history[0]["run_id"] == restored_records[0].run_id
    assert restarted.has_run_id(restored_records[0].run_id)


def test_workflow_execution_history_persistence_stays_bounded(tmp_path) -> None:
    state_path = tmp_path / "workflow_state.json"
    history: deque[dict[str, Any]] = deque()
    service = WorkflowStateService(
        OrchestrationStateStore(str(state_path)),
        execution_history=history,
        max_execution_history=2,
    )

    for run_number in range(1, 4):
        history.append(
            {
                "run_id": f"run-{run_number}",
                "workflow_name": "bounded-workflow",
                "trigger_type": "manual",
                "status": "success",
                "duration_ms": float(run_number),
                "timestamp": 1_720_000_000.0 + run_number,
            }
        )
    service.persist_state()

    assert [entry["run_id"] for entry in history] == ["run-2", "run-3"]

    payload = OrchestrationStateStore(str(state_path)).read_namespace("workflows")
    assert [entry["run_id"] for entry in payload["execution_history"]] == ["run-2", "run-3"]

    restarted_history: deque[dict[str, Any]] = deque()
    restarted = WorkflowStateService(
        OrchestrationStateStore(str(state_path)),
        execution_history=restarted_history,
        max_execution_history=2,
    )

    assert restarted.execution_history is restarted_history
    assert [record.run_id for record in restarted.list_execution_records()] == [
        "run-2",
        "run-3",
    ]
