"""Population tracker for agent evaluation statistics.

Maintains running statistics across agent populations, tracking scores
per metric and computing distributions on demand.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime

from agent33.evaluation.comparative.models import (
    AgentScore,
    PopulationStats,
)
from agent33.evaluation.comparative.percentile import PercentileCalculator

logger = logging.getLogger(__name__)

# Maximum number of score records kept per agent per metric
_MAX_SCORES_PER_AGENT_METRIC = 500


class PopulationTracker:
    """Track scores across a population of agents.

    Stores score history per agent per metric and computes population-level
    statistics on demand.
    """

    def __init__(self, max_scores_per_agent_metric: int = _MAX_SCORES_PER_AGENT_METRIC) -> None:
        # {metric_name: {agent_name: [scores]}}
        self._scores: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        self._records: dict[str, dict[str, list[AgentScore]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self._max_scores = max_scores_per_agent_metric
        self._last_updated: datetime | None = None

    @property
    def agent_names(self) -> set[str]:
        """All agent names that have recorded scores."""
        names: set[str] = set()
        for metric_agents in self._scores.values():
            names.update(metric_agents.keys())
        return names

    @property
    def metric_names(self) -> set[str]:
        """All metric names that have recorded scores."""
        return set(self._scores.keys())

    @property
    def population_size(self) -> int:
        """Number of distinct agents in the population."""
        return len(self.agent_names)

    def add_score(self, score: AgentScore) -> None:
        """Add an agent score observation to the population.

        Parameters
        ----------
        score:
            The agent score to record.
        """
        agent_scores = self._scores[score.metric_name][score.agent_name]
        agent_scores.append(score.value)
        agent_records = self._records[score.metric_name][score.agent_name]
        agent_records.append(score)
        # Bounded retention
        if len(agent_scores) > self._max_scores:
            del agent_scores[: len(agent_scores) - self._max_scores]
        if len(agent_records) > self._max_scores:
            del agent_records[: len(agent_records) - self._max_scores]
        self._last_updated = datetime.now(UTC)

    def add_scores(self, scores: list[AgentScore]) -> None:
        """Add multiple score observations at once."""
        for score in scores:
            self.add_score(score)

    def get_agent_mean(self, agent_name: str, metric_name: str) -> float | None:
        """Get the mean score for a specific agent on a specific metric.

        Returns ``None`` if no scores exist for this agent/metric pair.
        """
        scores = self._scores.get(metric_name, {}).get(agent_name)
        if not scores:
            return None
        return sum(scores) / len(scores)

    def get_agent_score_records(self, agent_name: str, metric_name: str) -> list[AgentScore]:
        """Return full score records for an agent/metric pair."""
        records = self._records.get(metric_name, {}).get(agent_name)
        if not records:
            return []
        return list(records)

    def get_latest_task_scores(
        self,
        agent_name: str,
        metric_name: str,
        *,
        task_ids: set[str] | None = None,
    ) -> dict[str, float]:
        """Return the latest score value for each task ID for an agent/metric pair."""
        latest: dict[str, float] = {}
        for record in self.get_agent_score_records(agent_name, metric_name):
            if record.task_id is None:
                continue
            if task_ids is not None and record.task_id not in task_ids:
                continue
            latest[record.task_id] = record.value
        return latest

    def get_agent_latest(self, agent_name: str, metric_name: str) -> float | None:
        """Get the most recent score for a specific agent on a specific metric."""
        scores = self._scores.get(metric_name, {}).get(agent_name)
        if not scores:
            return None
        return scores[-1]

    def get_population_means(self, metric_name: str) -> dict[str, float]:
        """Get mean scores for all agents on a specific metric.

        Returns
        -------
        dict[str, float]
            Mapping of agent name to mean score.
        """
        agent_map = self._scores.get(metric_name, {})
        return {agent: sum(scores) / len(scores) for agent, scores in agent_map.items() if scores}

    def compute_stats(self, metric_name: str) -> PopulationStats:
        """Compute descriptive statistics for a metric across the population.

        Uses each agent's mean score as the population data point.

        Parameters
        ----------
        metric_name:
            The metric to compute statistics for.

        Returns
        -------
        PopulationStats
            Population-level descriptive statistics.
        """
        means = self.get_population_means(metric_name)
        if not means:
            return PopulationStats(metric_name=metric_name)

        values = list(means.values())
        calc = PercentileCalculator
        raw = calc.compute_population_stats(metric_name, values)
        return PopulationStats(
            metric_name=metric_name,
            count=len(values),
            mean=raw["mean"],
            std_dev=raw["std_dev"],
            min_value=raw["min"],
            max_value=raw["max"],
            median=raw["median"],
            p25=raw["p25"],
            p75=raw["p75"],
        )

    def compute_all_stats(self) -> dict[str, PopulationStats]:
        """Compute statistics for all tracked metrics.

        Returns
        -------
        dict[str, PopulationStats]
            Mapping of metric name to population statistics.
        """
        return {metric: self.compute_stats(metric) for metric in self._scores}

    def get_agent_scores_count(self, agent_name: str) -> int:
        """Total number of score records for an agent across all metrics."""
        total = 0
        for metric_agents in self._scores.values():
            scores = metric_agents.get(agent_name, [])
            total += len(scores)
        return total

    def clear(self) -> None:
        """Remove all tracked scores."""
        self._scores.clear()
        self._records.clear()
        self._last_updated = None
