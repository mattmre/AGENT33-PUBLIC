"""SpawnerService: in-memory workflow store + execution orchestration (Phase 71).

Stores sub-agent workflow definitions in memory and executes them via the
existing DelegationManager (Phase 53). Tracks live execution state in an
in-memory dict keyed by execution_id.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agent33.spawner.models import (
    ExecutionNode,
    ExecutionTree,
    SubAgentWorkflow,
)

if TYPE_CHECKING:
    from agent33.agents.delegation import DelegationManager

logger = logging.getLogger(__name__)


class SpawnerService:
    """In-memory workflow CRUD + async execution via DelegationManager."""

    def __init__(self, delegation_manager: DelegationManager) -> None:
        self._delegation_manager = delegation_manager
        self._workflows: dict[str, SubAgentWorkflow] = {}
        self._executions: dict[str, ExecutionTree] = {}
        # Map execution_id -> background task so callers can fire-and-forget
        self._tasks: dict[str, asyncio.Task[None]] = {}

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_workflow(self, workflow: SubAgentWorkflow) -> SubAgentWorkflow:
        """Persist a workflow definition (in-memory). Returns the saved copy."""
        if workflow.id in self._workflows:
            raise ValueError(f"Workflow '{workflow.id}' already exists")
        self._workflows[workflow.id] = workflow
        logger.info("spawner_workflow_created id=%s name=%s", workflow.id, workflow.name)
        return workflow

    def get_workflow(self, workflow_id: str) -> SubAgentWorkflow | None:
        return self._workflows.get(workflow_id)

    def list_workflows(self) -> list[SubAgentWorkflow]:
        """Return all workflows sorted by created_at descending."""
        return sorted(
            self._workflows.values(),
            key=lambda w: w.created_at,
            reverse=True,
        )

    def delete_workflow(self, workflow_id: str) -> bool:
        """Delete a workflow. Returns True if it existed."""
        removed = self._workflows.pop(workflow_id, None)
        if removed is not None:
            logger.info("spawner_workflow_deleted id=%s", workflow_id)
            return True
        return False

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute_workflow(self, workflow_id: str) -> ExecutionTree:
        """Start executing a workflow asynchronously.

        Creates the execution tree with status=pending for all nodes, then
        launches a background task that delegates to each child agent.

        Returns the initial ExecutionTree (caller can poll for updates).
        """
        workflow = self._workflows.get(workflow_id)
        if workflow is None:
            raise ValueError(f"Workflow '{workflow_id}' not found")

        child_nodes = [ExecutionNode(agent_name=child.agent_name) for child in workflow.children]

        root = ExecutionNode(
            agent_name=workflow.parent_agent,
            children=child_nodes,
        )

        tree = ExecutionTree(
            workflow_id=workflow_id,
            root=root,
        )
        self._executions[tree.execution_id] = tree

        # Fire the background task
        task = asyncio.create_task(self._run_execution(tree, workflow))
        self._tasks[tree.execution_id] = task
        task.add_done_callback(lambda _t: self._tasks.pop(tree.execution_id, None))

        logger.info(
            "spawner_execution_started workflow_id=%s execution_id=%s children=%d",
            workflow_id,
            tree.execution_id,
            len(child_nodes),
        )
        return tree

    def get_execution(self, execution_id: str) -> ExecutionTree | None:
        return self._executions.get(execution_id)

    def get_latest_execution(self, workflow_id: str) -> ExecutionTree | None:
        """Return the most recent execution for a given workflow, or None."""
        candidates = [e for e in self._executions.values() if e.workflow_id == workflow_id]
        if not candidates:
            return None
        return max(candidates, key=lambda e: e.started_at or datetime.min.replace(tzinfo=UTC))

    async def _run_execution(
        self,
        tree: ExecutionTree,
        workflow: SubAgentWorkflow,
    ) -> None:
        """Background coroutine: run the parent then delegate to children."""
        from agent33.agents.delegation import DelegationRequest

        now = datetime.now(UTC)
        tree.status = "running"
        tree.started_at = now
        tree.root.status = "running"
        tree.root.started_at = now

        any_failed = False

        for i, child_config in enumerate(workflow.children):
            child_node = tree.root.children[i]
            child_node.status = "running"
            child_node.started_at = datetime.now(UTC)

            try:
                request = DelegationRequest(
                    parent_agent=workflow.parent_agent,
                    target_agent=child_config.agent_name,
                    inputs={
                        "system_prompt_override": child_config.system_prompt_override,
                        "tool_allowlist": child_config.tool_allowlist,
                        "autonomy_level": child_config.autonomy_level,
                        "isolation": child_config.isolation.value,
                        "pack_names": child_config.pack_names,
                    },
                    token_budget=4096,
                    timeout_seconds=120,
                    depth=1,
                )
                result = await self._delegation_manager.delegate(request)

                if result.status.value in ("completed",):
                    child_node.status = "completed"
                    summary = result.raw_response[:200] if result.raw_response else ""
                    child_node.result_summary = summary or None
                else:
                    child_node.status = "failed"
                    child_node.error = result.error or f"Delegation status: {result.status.value}"
                    any_failed = True

            except Exception as exc:
                logger.exception(
                    "spawner_child_execution_failed agent=%s",
                    child_config.agent_name,
                )
                child_node.status = "failed"
                child_node.error = str(exc)
                any_failed = True
            finally:
                child_node.completed_at = datetime.now(UTC)

        # Mark root and tree as completed/failed
        tree.root.completed_at = datetime.now(UTC)
        tree.root.status = "failed" if any_failed else "completed"
        tree.completed_at = datetime.now(UTC)
        tree.status = "failed" if any_failed else "completed"

        logger.info(
            "spawner_execution_finished execution_id=%s status=%s",
            tree.execution_id,
            tree.status,
        )

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def shutdown(self) -> None:
        """Cancel any in-flight execution tasks."""
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        logger.info("spawner_service_shutdown")
