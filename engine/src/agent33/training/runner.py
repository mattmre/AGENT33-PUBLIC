"""Training runner - executes rollouts with tracing and evaluation."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent33.agents.runtime import AgentRuntime
    from agent33.training.emitter import TraceEmitter
    from agent33.training.evaluator import SelfEvaluator
    from agent33.training.store import TrainingStore

logger = logging.getLogger(__name__)


class TrainingRunner:
    """Orchestrates individual rollout execution with tracing."""

    def __init__(
        self,
        runtime: AgentRuntime,
        emitter: TraceEmitter,
        evaluator: SelfEvaluator,
        store: TrainingStore,
    ) -> None:
        self._runtime = runtime
        self._emitter = emitter
        self._evaluator = evaluator
        self._store = store

    async def run_rollout(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Execute a single agent rollout with tracing and evaluation.

        Returns dict with rollout_id, output, reward, spans.
        """
        import json

        rollout_id = self._emitter.new_rollout()
        agent_name = self._runtime.definition.name

        # Emit prompt span
        self._emitter.emit_prompt(
            agent_name,
            [{"role": "user", "content": json.dumps(inputs)}],
        )

        # Execute agent
        try:
            result = await self._runtime.invoke(inputs)
            result_text = result.raw_response
        except Exception as exc:
            result_text = f"ERROR: {exc}"
            logger.warning("rollout %s failed: %s", rollout_id, exc)

        # Emit result span
        self._emitter.emit_result(agent_name, result_text)

        # Self-evaluate
        task_context = json.dumps(inputs)
        reward = await self._evaluator.evaluate(result_text, task_context)

        # Emit reward span
        self._emitter.emit_reward(agent_name, reward)

        # Collect and store
        spans = self._emitter.collect()
        await self._store.store_rollout(
            rollout_id=rollout_id,
            agent_name=agent_name,
            spans=spans,
            total_reward=reward,
        )

        return {
            "rollout_id": rollout_id,
            "agent_name": agent_name,
            "output": result_text,
            "reward": reward,
            "span_count": len(spans),
        }

    async def run_batch(
        self, input_list: list[dict[str, Any]], parallel: int = 4
    ) -> list[dict[str, Any]]:
        """Run multiple rollouts with bounded parallelism."""
        semaphore = asyncio.Semaphore(parallel)

        async def _run(inputs: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                return await self.run_rollout(inputs)

        tasks = [_run(inp) for inp in input_list]
        return await asyncio.gather(*tasks, return_exceptions=False)
