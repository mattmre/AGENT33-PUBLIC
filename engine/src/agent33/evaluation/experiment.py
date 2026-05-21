"""Experiment orchestrator for multi-trial evaluations.

Runs the full matrix of (task x agent x model x skills_mode) combinations,
collects results, and computes skills impact metrics.
"""

from __future__ import annotations

import itertools
import logging
from datetime import UTC, datetime
from typing import Any

from agent33.evaluation.multi_trial import (
    ExperimentConfig,
    MultiTrialExecutor,
    MultiTrialResult,
    MultiTrialRun,
    SkillsImpact,
)

logger = logging.getLogger(__name__)


class ExperimentRunner:
    """Orchestrates multi-trial experiments across task/agent/model/skills matrix."""

    def __init__(self, executor: MultiTrialExecutor) -> None:
        self._executor = executor

    async def run_experiment(self, config: ExperimentConfig) -> MultiTrialRun:
        """Run the full experiment matrix.

        Iterates over all combinations of (task, agent, model, skills_mode)
        and runs ``config.trials_per_combination`` trials for each.
        """
        run = MultiTrialRun(config=config, status="running")

        try:
            combinations = list(
                itertools.product(
                    config.tasks,
                    config.agents,
                    config.models,
                    config.skills_modes,
                )
            )
            logger.info(
                "experiment_started run_id=%s combinations=%d trials_each=%d",
                run.run_id,
                len(combinations),
                config.trials_per_combination,
            )

            for task_id, agent, model, skills_enabled in combinations:
                result = await self._executor.execute_multi_trial(
                    task_id=task_id,
                    agent=agent,
                    model=model,
                    skills_enabled=skills_enabled,
                    num_trials=config.trials_per_combination,
                )
                run.results.append(result)

            # Compute skills impacts by pairing with/without results
            run.skills_impacts = self.compute_skills_impacts(run.results)
            run.status = "completed"
            run.completed_at = datetime.now(UTC)

            logger.info(
                "experiment_completed run_id=%s results=%d impacts=%d",
                run.run_id,
                len(run.results),
                len(run.skills_impacts),
            )
        except Exception:
            run.status = "failed"
            run.completed_at = datetime.now(UTC)
            logger.exception("experiment_failed run_id=%s", run.run_id)
            raise

        return run

    @staticmethod
    def compute_skills_impacts(
        results: list[MultiTrialResult],
    ) -> list[SkillsImpact]:
        """Pair with/without-skills results and compute impact metrics.

        Groups results by (task_id, agent, model), then for each group
        that has both skills_enabled=True and skills_enabled=False,
        computes the skills impact.
        """
        groups: dict[tuple[str, str, str], dict[bool, MultiTrialResult]] = {}
        for r in results:
            key = (r.task_id, r.agent, r.model)
            if key not in groups:
                groups[key] = {}
            groups[key][r.skills_enabled] = r

        impacts: list[SkillsImpact] = []
        for _key, modes in groups.items():
            if True in modes and False in modes:
                impact = MultiTrialExecutor.compute_skills_impact(
                    with_skills=modes[True],
                    without_skills=modes[False],
                )
                impacts.append(impact)

        return impacts

    def generate_comparison_matrix(self, run: MultiTrialRun) -> dict[str, Any]:
        """Generate a comparison matrix of results across dimensions.

        Returns a nested dict keyed by ``agent/model`` -> ``task_id``
        -> ``with_skills`` / ``without_skills``.
        """
        matrix: dict[str, dict[str, dict[str, Any]]] = {}
        for r in run.results:
            key = f"{r.agent}/{r.model}"
            if key not in matrix:
                matrix[key] = {}
            skills_key = "with_skills" if r.skills_enabled else "without_skills"
            if r.task_id not in matrix[key]:
                matrix[key][r.task_id] = {}
            matrix[key][r.task_id][skills_key] = {
                "pass_rate": r.pass_rate,
                "variance": r.variance,
                "trials": len(r.trials),
            }
        return matrix
