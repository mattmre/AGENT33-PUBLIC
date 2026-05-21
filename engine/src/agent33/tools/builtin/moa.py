"""Mixture-of-Agents (MoA) tool.

Wraps the MoA workflow template as a standard AGENT-33 tool so agents can
invoke multi-model ensemble reasoning through the normal tool interface.

Phase 58 adds support for multi-round proposer layers, temperature diversity,
and cost estimation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

import structlog

from agent33.tools.base import ToolContext, ToolResult
from agent33.workflows.actions.invoke_agent import has_registered_agent_handler
from agent33.workflows.executor import WorkflowExecutor
from agent33.workflows.templates.mixture_of_agents import (
    build_moa_workflow,
    estimate_moa_cost,
    format_moa_result,
)

logger = structlog.get_logger()

if TYPE_CHECKING:
    from agent33.observability.replay import ExecutionReplay
    from agent33.workflows.checkpoint import CheckpointManager


def _resolve_workflow_agent_name(model_name: str) -> str:
    """Resolve a model identifier to a workflow agent name.

    Prefer an exact executable workflow agent. If one is not registered, fall
    back to the shared ``__default__`` bridge. Raise ``ValueError`` when
    neither path is available.
    """
    if has_registered_agent_handler(model_name):
        return model_name

    if has_registered_agent_handler("__default__"):
        return "__default__"

    raise ValueError(f"No workflow agent or __default__ bridge available for model '{model_name}'")


class MoATool:
    """Execute a Mixture-of-Agents workflow via the standard tool protocol.

    Parameters accepted in ``params``:
        query (str, required): The question or instruction to answer.
        reference_models (list[str], optional): Model IDs for the parallel
            reference layer.  Falls back to ``default_reference_models``.
        aggregator (str, optional): Model ID for the aggregator step.
            Falls back to ``default_aggregator_model``.
        reference_temperature (float, optional): Temperature for reference
            models.  Defaults to ``default_reference_temperature``.
        aggregator_temperature (float, optional): Temperature for the
            aggregator.  Defaults to ``default_aggregator_temperature``.
        rounds (int, optional): Number of proposer rounds (default 1).
        temperature_diversity (bool, optional): Spread temperatures across
            proposers for response variety (default False).
        estimate_only (bool, optional): If True, return a cost estimate
            without executing the workflow (default False).
    """

    def __init__(
        self,
        default_reference_models: list[str] | None = None,
        default_aggregator_model: str = "",
        default_reference_temperature: float = 0.6,
        default_aggregator_temperature: float = 0.4,
        execution_replay: ExecutionReplay | None = None,
        checkpoint_manager: CheckpointManager | None = None,
    ) -> None:
        self._default_reference_models = default_reference_models or []
        self._default_aggregator_model = default_aggregator_model
        self._default_reference_temperature = default_reference_temperature
        self._default_aggregator_temperature = default_aggregator_temperature
        self._execution_replay = execution_replay
        self._checkpoint_manager = checkpoint_manager

    @property
    def name(self) -> str:
        return "mixture_of_agents"

    @property
    def description(self) -> str:
        return (
            "Run a Mixture-of-Agents ensemble: query multiple models in "
            "parallel and synthesize their responses through an aggregator. "
            "Supports multi-round proposer layers and temperature diversity."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The question or instruction to answer.",
                },
                "reference_models": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Model identifiers for the parallel reference layer.",
                },
                "aggregator": {
                    "type": "string",
                    "description": "Model identifier for the aggregator step.",
                },
                "reference_temperature": {
                    "type": "number",
                    "description": "Base sampling temperature for reference models.",
                },
                "aggregator_temperature": {
                    "type": "number",
                    "description": "Sampling temperature for the aggregator.",
                },
                "rounds": {
                    "type": "integer",
                    "description": "Number of proposer rounds (1 = single layer).",
                    "minimum": 1,
                    "maximum": 5,
                },
                "temperature_diversity": {
                    "type": "boolean",
                    "description": "Spread temperatures across proposers for variety.",
                },
                "estimate_only": {
                    "type": "boolean",
                    "description": "Return cost estimate without executing.",
                },
            },
            "required": ["query"],
        }

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        """Build and run a MoA workflow, returning the aggregated answer."""
        query: str = params.get("query", "").strip()
        if not query:
            return ToolResult.fail("No query provided")

        reference_models: list[str] = params.get(
            "reference_models", self._default_reference_models
        )
        if not reference_models:
            return ToolResult.fail(
                "No reference models provided and no defaults configured. "
                "Set MOA_REFERENCE_MODELS or pass reference_models."
            )

        aggregator: str = params.get("aggregator", self._default_aggregator_model)
        if not aggregator:
            return ToolResult.fail(
                "No aggregator model provided and no default configured. "
                "Set MOA_AGGREGATOR_MODEL or pass aggregator."
            )

        ref_temp: float = params.get("reference_temperature", self._default_reference_temperature)
        agg_temp: float = params.get(
            "aggregator_temperature", self._default_aggregator_temperature
        )
        rounds: int = params.get("rounds", 1)
        temp_diversity: bool = params.get("temperature_diversity", False)
        estimate_only: bool = params.get("estimate_only", False)

        logger.info(
            "moa_tool_invoked",
            query_len=len(query),
            reference_models=reference_models,
            aggregator=aggregator,
            rounds=rounds,
            temperature_diversity=temp_diversity,
            estimate_only=estimate_only,
        )

        # Cost estimation mode
        if estimate_only:
            try:
                cost = estimate_moa_cost(
                    query=query,
                    reference_models=reference_models,
                    aggregator_model=aggregator,
                    rounds=rounds,
                )
                return ToolResult.ok(
                    f"Estimated cost: ${cost.total_usd} USD "
                    f"({cost.proposer_count} proposers x {cost.rounds} rounds "
                    f"+ 1 aggregator, status={cost.status.value})"
                )
            except Exception as exc:
                return ToolResult.fail(f"Cost estimation failed: {exc}")

        try:
            unique_models = set(reference_models)
            unique_models.add(aggregator)
            resolved_agents = {
                model: _resolve_workflow_agent_name(model) for model in unique_models
            }

            workflow = build_moa_workflow(
                query=query,
                reference_models=reference_models,
                aggregator_model=aggregator,
                reference_temperature=ref_temp,
                aggregator_temperature=agg_temp,
                rounds=rounds,
                temperature_diversity=temp_diversity,
                agent_resolver=lambda model_name: resolved_agents[model_name],
            )
        except ValueError as exc:
            return ToolResult.fail(f"Failed to build MoA workflow: {exc}")

        session_suffix = context.session_id.strip() or "adhoc"
        run_id = f"moa-tool-{session_suffix}-{uuid4().hex}"[-128:]
        executor = WorkflowExecutor(
            definition=workflow,
            tenant_id=context.tenant_id,
            run_id=run_id,
            replay=self._execution_replay,
            checkpoint_manager=self._checkpoint_manager,
        )

        try:
            result = await executor.execute()
        except Exception as exc:
            logger.error("moa_workflow_execution_error", error=str(exc))
            return ToolResult.fail(f"MoA workflow execution failed: {exc}")

        if result.status.value == "failed":
            error_msgs = [sr.error for sr in result.step_results if sr.error]
            return ToolResult.fail(
                f"MoA workflow failed: {'; '.join(error_msgs) or 'unknown error'}"
            )

        aggregated = format_moa_result(result.outputs)
        logger.info(
            "moa_tool_complete",
            status=result.status.value,
            steps_executed=len(result.steps_executed),
            duration_ms=result.duration_ms,
            run_id=run_id,
            replay_enabled=self._execution_replay is not None,
            checkpoint_enabled=self._checkpoint_manager is not None,
        )
        return ToolResult.ok(aggregated)
