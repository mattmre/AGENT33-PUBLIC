"""Test harness for workflow definitions -- dry-run and mock execution."""

from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING, Any

from agent33.workflows.dag import DAGBuilder
from agent33.workflows.definition import WorkflowDefinition, WorkflowStep

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True, slots=True)
class DryRunStepResult:
    """A single step that would execute during a dry run."""

    step_id: str
    action: str
    agent: str | None
    inputs: dict[str, Any]
    group_index: int


@dataclasses.dataclass(frozen=True, slots=True)
class DryRunResult:
    """Result of a workflow dry run showing execution plan without side effects."""

    workflow_name: str
    total_steps: int
    execution_order: list[str]
    parallel_groups: list[list[str]]
    steps: list[DryRunStepResult]


@dataclasses.dataclass(frozen=True, slots=True)
class StepResult:
    """Result of executing a single workflow step."""

    step_id: str
    output: dict[str, Any]
    skipped: bool = False


@dataclasses.dataclass(frozen=True, slots=True)
class WorkflowResult:
    """Result of a complete workflow execution."""

    workflow_name: str
    success: bool
    step_results: list[StepResult]
    outputs: dict[str, Any]


class WorkflowTestHarness:
    """Loads and tests workflow definitions with dry-run and mock support."""

    def __init__(self) -> None:
        self._definition: WorkflowDefinition | None = None

    def load_workflow(self, path: str | Path) -> WorkflowDefinition:
        """Load a workflow definition from a file.

        Returns the loaded definition for inspection.
        """
        self._definition = WorkflowDefinition.load_from_file(path)
        logger.info("Loaded workflow: %s v%s", self._definition.name, self._definition.version)
        return self._definition

    def load_definition(self, definition: WorkflowDefinition) -> None:
        """Load a pre-built workflow definition directly."""
        self._definition = definition

    def dry_run(self, inputs: dict[str, Any] | None = None) -> DryRunResult:
        """Execute a dry run of the workflow.

        Analyzes the DAG and returns the execution plan without performing
        any actual side effects.

        Parameters
        ----------
        inputs:
            Workflow inputs (used for display only during dry run).

        Returns
        -------
        DryRunResult:
            The planned execution order and step details.
        """
        defn = self._require_definition()
        inputs = inputs or {}

        dag = DAGBuilder(defn.steps).build()
        topo_order = dag.topological_order()
        groups = dag.parallel_groups()

        step_map = {s.id: s for s in defn.steps}
        group_index_map: dict[str, int] = {}
        for idx, group in enumerate(groups):
            for sid in group:
                group_index_map[sid] = idx

        dry_steps: list[DryRunStepResult] = []
        for sid in topo_order:
            step = step_map[sid]
            merged_inputs = dict(step.inputs)
            merged_inputs.update(inputs)
            dry_steps.append(
                DryRunStepResult(
                    step_id=sid,
                    action=step.action.value,
                    agent=step.agent,
                    inputs=merged_inputs,
                    group_index=group_index_map.get(sid, 0),
                )
            )

        return DryRunResult(
            workflow_name=defn.name,
            total_steps=len(topo_order),
            execution_order=topo_order,
            parallel_groups=groups,
            steps=dry_steps,
        )

    async def run_with_mocks(
        self,
        inputs: dict[str, Any] | None = None,
        mock_agents: dict[str, dict[str, Any]] | None = None,
    ) -> WorkflowResult:
        """Run the workflow using mock agent outputs.

        Parameters
        ----------
        inputs:
            Workflow-level inputs passed to each step.
        mock_agents:
            Mapping of ``agent_name -> output_dict``.  When a step invokes
            an agent listed here the mock output is used instead of calling
            a real LLM.

        Returns
        -------
        WorkflowResult:
            The aggregated result of all steps.
        """
        defn = self._require_definition()
        inputs = inputs or {}
        mock_agents = mock_agents or {}

        dag = DAGBuilder(defn.steps).build()
        topo_order = dag.topological_order()
        step_map = {s.id: s for s in defn.steps}

        step_results: list[StepResult] = []
        context: dict[str, Any] = dict(inputs)

        for sid in topo_order:
            step = step_map[sid]
            output = self._execute_mock_step(step, context, mock_agents)
            step_results.append(StepResult(step_id=sid, output=output))
            context[sid] = output

        return WorkflowResult(
            workflow_name=defn.name,
            success=True,
            step_results=step_results,
            outputs=context,
        )

    # -- internals ------------------------------------------------------------

    def _require_definition(self) -> WorkflowDefinition:
        if self._definition is None:
            msg = "No workflow loaded. Call load_workflow() or load_definition() first."
            raise RuntimeError(msg)
        return self._definition

    @staticmethod
    def _execute_mock_step(
        step: WorkflowStep,
        context: dict[str, Any],
        mock_agents: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """Resolve a single step using mock data."""
        if step.agent and step.agent in mock_agents:
            return dict(mock_agents[step.agent])

        # For non-agent steps, return the step's declared outputs or an empty dict.
        return dict(step.outputs) if step.outputs else {}
