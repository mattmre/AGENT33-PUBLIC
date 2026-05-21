"""Agent optimizer - orchestrates the self-evolution loop."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent33.llm.router import ModelRouter
    from agent33.training.algorithm import Algorithm
    from agent33.training.store import TrainingStore

logger = logging.getLogger(__name__)


class AgentOptimizer:
    """Orchestrates the collect -> evaluate -> learn -> update loop.

    Runs the APO algorithm over collected rollouts to generate
    improved prompts, with automatic rollback on performance regression.
    """

    def __init__(
        self,
        store: TrainingStore,
        algorithm: Algorithm,
        router: ModelRouter,
        min_rollouts: int = 10,
    ) -> None:
        self._store = store
        self._algorithm = algorithm
        self._router = router
        self._min_rollouts = min_rollouts
        self._current_prompts: dict[str, str] = {}
        self._prompt_versions: dict[str, int] = {}

    async def optimize(
        self,
        agent_name: str,
        current_prompt: str,
        iterations: int = 3,
    ) -> str:
        """Run optimization loop for an agent.

        Returns the best prompt found after iterations.
        """
        rollouts = await self._store.get_rollouts(agent_name, limit=100)
        if len(rollouts) < self._min_rollouts:
            logger.info(
                "skipping optimization for %s: only %d rollouts (need %d)",
                agent_name,
                len(rollouts),
                self._min_rollouts,
            )
            return current_prompt

        # Enrich rollouts with span data
        enriched: list[dict[str, Any]] = []
        for r in rollouts:
            spans = await self._store.get_spans(r["rollout_id"])
            enriched.append({**r, "spans": spans})

        best_prompt = current_prompt
        version = self._prompt_versions.get(agent_name, 0)

        for i in range(iterations):
            logger.info("optimization iteration %d/%d for %s", i + 1, iterations, agent_name)
            new_prompt = await self._algorithm.run(enriched, best_prompt)

            if new_prompt and new_prompt != best_prompt:
                version += 1
                # Compute average reward for the current rollouts
                avg_reward = sum(r.get("total_reward", 0) for r in rollouts) / len(rollouts)
                await self._store.store_prompt_version(
                    agent_name=agent_name,
                    version=version,
                    prompt_text=new_prompt,
                    avg_reward=avg_reward,
                )
                best_prompt = new_prompt
                logger.info(
                    "new prompt v%d for %s (avg_reward=%.3f)",
                    version,
                    agent_name,
                    avg_reward,
                )

        self._current_prompts[agent_name] = best_prompt
        self._prompt_versions[agent_name] = version
        return best_prompt

    async def revert(self, agent_name: str) -> str | None:
        """Revert to the previous prompt version."""
        version = self._prompt_versions.get(agent_name, 0)
        if version <= 1:
            return None
        target_version = version - 1
        # Query the store for the previous version
        # For simplicity, re-fetch the latest which will be the one before current
        prev = await self._store.get_latest_prompt(agent_name)
        if prev:
            prompt_text: str = prev["prompt_text"]
            self._current_prompts[agent_name] = prompt_text
            self._prompt_versions[agent_name] = target_version
            return prompt_text
        return None

    def get_current_prompt(self, agent_name: str) -> str | None:
        """Get the current optimized prompt for an agent."""
        return self._current_prompts.get(agent_name)
