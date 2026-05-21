"""Replay/checkpoint propagation tests for secondary workflow executor paths."""

from __future__ import annotations

import copy
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from agent33.api.routes.moa import MoAExecuteRequest
from agent33.api.routes.moa import execute_workflow as execute_moa_workflow
from agent33.api.routes.step_retry import StepRetryRequest, retry_workflow_step
from agent33.observability.replay import ExecutionReplay
from agent33.tools.base import ToolContext
from agent33.tools.builtin.moa import MoATool
from agent33.workflows.actions.invoke_agent import register_agent
from agent33.workflows.definition import (
    StepAction,
    WorkflowDefinition,
    WorkflowExecution,
    WorkflowStep,
)
from agent33.workflows.executor import WorkflowExecutor


class RecordingCheckpointManager:
    """Test double that records checkpoint calls and exposes saved state."""

    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []
        self.loaded: list[str] = []

    async def load_checkpoint(self, workflow_id: str) -> dict[str, Any] | None:
        self.loaded.append(workflow_id)
        return None

    async def save_checkpoint(
        self,
        workflow_id: str,
        step_id: str,
        state: dict[str, Any],
    ) -> str:
        checkpoint_id = f"checkpoint-{len(self.saved) + 1}"
        self.saved.append(
            {
                "id": checkpoint_id,
                "workflow_id": workflow_id,
                "step_id": step_id,
                "state": copy.deepcopy(state),
            }
        )
        return checkpoint_id


def _request_with_runtime_services(
    replay: ExecutionReplay,
    checkpoint_manager: RecordingCheckpointManager,
) -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                execution_replay=replay,
                checkpoint_manager=checkpoint_manager,
                agent_registry=None,
                model_router=None,
            )
        )
    )


def _register_agent(name: str, response: str) -> None:
    async def handler(inputs: dict[str, Any]) -> dict[str, Any]:
        return {"result": f"{response}:{inputs.get('prompt', '')}"}

    register_agent(name, handler)


async def test_sub_workflow_inherits_replay_and_checkpoint_services() -> None:
    replay = ExecutionReplay()
    checkpoints = RecordingCheckpointManager()
    parent = WorkflowDefinition(
        name="parent-workflow",
        version="1.0.0",
        execution=WorkflowExecution(),
        steps=[
            WorkflowStep(
                id="nested",
                action=StepAction.SUB_WORKFLOW,
                sub_workflow={
                    "name": "child-workflow",
                    "version": "1.0.0",
                    "steps": [
                        {
                            "id": "child_transform",
                            "action": "transform",
                            "inputs": {"data": 42},
                        }
                    ],
                },
            )
        ],
    )

    result = await WorkflowExecutor(
        parent,
        run_id="parent-run",
        replay=replay,
        checkpoint_manager=checkpoints,
        tenant_id="tenant-a",
    ).execute()

    assert result.status.value == "success"
    assert result.outputs["outputs"]["result"] == 42
    assert [step.step_id for step in replay.get_steps("parent-run")] == ["nested"]
    assert [step.step_id for step in replay.get_steps("parent-run:sub:nested")] == [
        "child_transform"
    ]
    assert {entry["workflow_id"] for entry in checkpoints.saved} == {
        "parent-run",
        "parent-run:sub:nested",
    }


async def test_step_retry_records_replay_and_checkpoint_with_traceable_retry_id() -> None:
    replay = ExecutionReplay()
    checkpoints = RecordingCheckpointManager()
    request = _request_with_runtime_services(replay, checkpoints)
    body = StepRetryRequest(
        action="transform",
        inputs={"data": 84},
        state={"prior": "state"},
    )

    response = await retry_workflow_step(
        run_id="original-run",
        step_id="retry_step",
        body=body,
        request=request,  # type: ignore[arg-type]
    )

    retry_run_id = response["retry_run_id"]
    assert response["status"] == "success"
    assert response["outputs"] == {"result": 84}
    assert response["replay_enabled"] is True
    assert response["checkpoint_enabled"] is True
    assert retry_run_id.startswith("original-run-step-retry-retry_step-")
    assert [step.step_id for step in replay.get_steps(retry_run_id)] == ["retry_step"]
    assert checkpoints.saved[0]["workflow_id"] == retry_run_id
    assert checkpoints.saved[0]["state"]["__retry_metadata"] == {
        "parent_run_id": "original-run",
        "step_id": "retry_step",
        "retry_run_id": retry_run_id,
    }
    assert checkpoints.loaded == []


async def test_moa_api_route_records_replay_and_checkpoint() -> None:
    replay = ExecutionReplay()
    checkpoints = RecordingCheckpointManager()
    request = _request_with_runtime_services(replay, checkpoints)
    suffix = uuid4().hex
    reference_model = f"ref_model_{suffix}"
    aggregator_model = f"agg_model_{suffix}"
    _register_agent(reference_model, "reference")
    _register_agent(aggregator_model, "aggregate")

    response = await execute_moa_workflow(
        MoAExecuteRequest(
            query="What is reliable completion evidence?",
            reference_models=[reference_model],
            aggregator_model=aggregator_model,
            tenant_id="tenant-a",
        ),
        request,  # type: ignore[arg-type]
    )

    run_id = response["run_id"]
    replayed_steps = replay.get_steps(run_id)
    assert response["status"] == "success"
    assert response["replay_enabled"] is True
    assert response["checkpoint_enabled"] is True
    assert response["result"].startswith("aggregate:")
    assert [step.step_id for step in replayed_steps] == [
        f"ref_{reference_model}",
        "moa_aggregator",
    ]
    assert [entry["workflow_id"] for entry in checkpoints.saved] == [run_id, run_id]
    assert [entry["step_id"] for entry in checkpoints.saved] == [
        f"ref_{reference_model}",
        "moa_aggregator",
    ]


async def test_moa_tool_uses_injected_replay_and_checkpoint_services() -> None:
    replay = ExecutionReplay()
    checkpoints = RecordingCheckpointManager()
    suffix = uuid4().hex
    reference_model = f"tool_ref_{suffix}"
    aggregator_model = f"tool_agg_{suffix}"
    _register_agent(reference_model, "tool-reference")
    _register_agent(aggregator_model, "tool-aggregate")
    tool = MoATool(
        default_reference_models=[reference_model],
        default_aggregator_model=aggregator_model,
        execution_replay=replay,
        checkpoint_manager=checkpoints,
    )

    result = await tool.execute(
        {"query": "How should tools prove workflow execution?"},
        ToolContext(tenant_id="tenant-a", session_id="session-a"),
    )

    assert result.success is True
    assert result.output.startswith("tool-aggregate:")
    assert len(checkpoints.saved) == 2
    run_id = checkpoints.saved[0]["workflow_id"]
    assert run_id.startswith("moa-tool-session-a-")
    assert [step.step_id for step in replay.get_steps(run_id)] == [
        f"ref_{reference_model}",
        "moa_aggregator",
    ]
