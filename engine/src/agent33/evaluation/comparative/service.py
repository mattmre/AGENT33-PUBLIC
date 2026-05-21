"""Comparative evaluation service.

Orchestrates evaluation runs, maintains the agent leaderboard, and
provides the main entry point for the group-relative scoring subsystem.
This service ties together the Elo calculator, percentile calculator,
population tracker, and agent comparator.
"""

from __future__ import annotations

import logging

from agent33.evaluation.comparative.comparator import AgentComparator
from agent33.evaluation.comparative.elo import EloCalculator
from agent33.evaluation.comparative.models import (
    AgentProfile,
    AgentScore,
    BundleLeaderboardSnapshot,
    BundleRankingEntry,
    ComparisonResult,
    EloRating,
    LeaderboardSnapshot,
    RankingEntry,
)
from agent33.evaluation.comparative.percentile import PercentileCalculator
from agent33.evaluation.comparative.population import PopulationTracker

logger = logging.getLogger(__name__)

# Maximum number of leaderboard snapshots to retain
_MAX_SNAPSHOTS = 200
_BUNDLE_TASK_SEPARATOR = "::"


class ComparativeEvaluationService:
    """Orchestrate comparative evaluation across an agent population.

    This is the primary interface for the group-relative scoring system.
    It manages Elo ratings, population statistics, the leaderboard, and
    agent profiles.
    """

    def __init__(
        self,
        elo_k_factor: float = 32.0,
        min_population_size: int = 2,
        confidence_level: float = 0.95,
    ) -> None:
        self._elo = EloCalculator(k_factor=elo_k_factor)
        self._population = PopulationTracker()
        self._comparator = AgentComparator(
            population=self._population,
            confidence_level=confidence_level,
        )
        self._ratings: dict[str, EloRating] = {}
        self._snapshots: list[LeaderboardSnapshot] = []
        self._min_population_size = min_population_size

    @property
    def population_tracker(self) -> PopulationTracker:
        """Access the underlying population tracker."""
        return self._population

    @property
    def elo_calculator(self) -> EloCalculator:
        """Access the underlying Elo calculator."""
        return self._elo

    # ------------------------------------------------------------------
    # Score ingestion
    # ------------------------------------------------------------------

    def record_scores(self, scores: list[AgentScore]) -> None:
        """Record agent scores into the population tracker.

        Parameters
        ----------
        scores:
            List of agent score observations to record.
        """
        self._population.add_scores(scores)
        for score in scores:
            if score.agent_name not in self._ratings:
                self._ratings[score.agent_name] = self._elo.create_rating(score.agent_name)
        logger.info(
            "comparative_scores_recorded count=%d agents=%d",
            len(scores),
            self._population.population_size,
        )

    @staticmethod
    def build_bundle_task_id(bundle_id: str, task_id: str) -> str:
        """Return a canonical task ID namespaced to one persisted bundle."""
        return f"{bundle_id}{_BUNDLE_TASK_SEPARATOR}{task_id}"

    def record_bundle_scores(
        self,
        bundle_id: str,
        scores: list[AgentScore],
        *,
        allowed_task_ids: set[str],
    ) -> list[AgentScore]:
        """Validate and record bundle-scoped scores against persisted task IDs."""
        canonical_scores: list[AgentScore] = []
        invalid_task_ids: set[str] = set()
        for score in scores:
            task_id = score.task_id
            if task_id is None:
                invalid_task_ids.add("<missing>")
            elif task_id not in allowed_task_ids:
                invalid_task_ids.add(task_id)

        if invalid_task_ids:
            invalid_summary = ", ".join(sorted(invalid_task_ids))
            raise ValueError("Unknown bundle task IDs: " + invalid_summary)

        for score in scores:
            task_id = score.task_id
            if task_id is None:
                raise ValueError("Unknown bundle task IDs: <missing>")
            canonical_scores.append(
                score.model_copy(update={"task_id": self.build_bundle_task_id(bundle_id, task_id)})
            )

        self.record_scores(canonical_scores)
        return canonical_scores

    # ------------------------------------------------------------------
    # Comparative evaluation
    # ------------------------------------------------------------------

    def run_pairwise_evaluation(
        self,
        agent_a: str,
        agent_b: str,
        metric_name: str,
    ) -> ComparisonResult | None:
        """Run a pairwise comparison and update Elo ratings.

        Parameters
        ----------
        agent_a:
            Name of the first agent.
        agent_b:
            Name of the second agent.
        metric_name:
            The metric to compare on.

        Returns
        -------
        ComparisonResult or None
            The comparison result, or None if data is insufficient.
        """
        result = self._comparator.compare_agents(agent_a, agent_b, metric_name)
        if result is None:
            return None

        # Ensure both agents have Elo ratings
        if agent_a not in self._ratings:
            self._ratings[agent_a] = self._elo.create_rating(agent_a)
        if agent_b not in self._ratings:
            self._ratings[agent_b] = self._elo.create_rating(agent_b)

        # Update Elo
        self._elo.update_ratings(
            self._ratings[agent_a],
            self._ratings[agent_b],
            result.outcome,
        )
        return result

    def run_round_robin(self, metric_name: str) -> list[ComparisonResult]:
        """Run pairwise comparisons for all agent pairs on a metric.

        Each pair is compared once, and Elo ratings are updated
        accordingly. Requires at least ``min_population_size`` agents.

        Parameters
        ----------
        metric_name:
            The metric to evaluate on.

        Returns
        -------
        list[ComparisonResult]
            All pairwise comparison results.
        """
        agents = sorted(self._population.agent_names)
        if len(agents) < self._min_population_size:
            logger.warning(
                "comparative_insufficient_population size=%d min=%d",
                len(agents),
                self._min_population_size,
            )
            return []

        results: list[ComparisonResult] = []
        for i, agent_a in enumerate(agents):
            for agent_b in agents[i + 1 :]:
                result = self.run_pairwise_evaluation(agent_a, agent_b, metric_name)
                if result is not None:
                    results.append(result)
        return results

    def run_bundle_round_robin(
        self,
        bundle_id: str,
        metric_name: str,
    ) -> tuple[list[ComparisonResult], BundleLeaderboardSnapshot]:
        """Run pairwise comparisons over task-aligned scores for one synthetic bundle."""
        leaderboard = self.generate_bundle_leaderboard(bundle_id, metric_name)
        canonical_task_ids = {
            self.build_bundle_task_id(bundle_id, task_id) for task_id in leaderboard.task_ids
        }
        agents = [entry.agent_name for entry in leaderboard.entries]
        results: list[ComparisonResult] = []
        for index, agent_a in enumerate(agents):
            for agent_b in agents[index + 1 :]:
                result = self._comparator.compare_agents_on_task_subset(
                    agent_a,
                    agent_b,
                    metric_name,
                    canonical_task_ids,
                )
                if result is not None:
                    results.append(result)
        return results, leaderboard

    # ------------------------------------------------------------------
    # Leaderboard
    # ------------------------------------------------------------------

    def generate_leaderboard(self) -> LeaderboardSnapshot:
        """Generate a leaderboard snapshot from current Elo ratings.

        Agents are ranked by Elo rating (descending). Percentile ranks
        are computed relative to the Elo rating population.

        Returns
        -------
        LeaderboardSnapshot
            The current leaderboard.
        """
        if not self._ratings:
            snapshot = LeaderboardSnapshot(entries=[], population_size=0)
            self._store_snapshot(snapshot)
            return snapshot

        # Sort agents by Elo rating descending
        sorted_agents = sorted(
            self._ratings.values(),
            key=lambda r: r.rating,
            reverse=True,
        )

        # Compute percentile ranks based on Elo ratings
        elo_scores = {r.agent_name: r.rating for r in sorted_agents}
        percentiles = PercentileCalculator.compute_percentile_ranks(elo_scores)

        entries: list[RankingEntry] = []
        for rank, rating in enumerate(sorted_agents, start=1):
            entries.append(
                RankingEntry(
                    rank=rank,
                    agent_name=rating.agent_name,
                    elo_rating=round(rating.rating, 2),
                    percentile=round(percentiles.get(rating.agent_name, 0.0), 2),
                    total_evaluations=rating.games_played,
                    win_count=rating.win_count,
                    loss_count=rating.loss_count,
                    draw_count=rating.draw_count,
                )
            )

        snapshot = LeaderboardSnapshot(
            entries=entries,
            population_size=len(entries),
        )
        self._store_snapshot(snapshot)
        return snapshot

    def generate_bundle_leaderboard(
        self,
        bundle_id: str,
        metric_name: str,
    ) -> BundleLeaderboardSnapshot:
        """Generate a task-aligned leaderboard for one persisted synthetic bundle."""
        task_scores_by_agent = self._get_bundle_task_scores(bundle_id, metric_name)
        if len(task_scores_by_agent) < self._min_population_size:
            raise ValueError(
                "At least two agents with recorded bundle scores are required for evaluation"
            )

        common_task_ids = self._get_common_bundle_task_ids(task_scores_by_agent)
        if not common_task_ids:
            raise ValueError(
                "No task-aligned bundle scores are shared across the agent population"
            )

        average_scores = {
            agent_name: (
                sum(task_scores[task_id] for task_id in common_task_ids) / len(common_task_ids)
            )
            for agent_name, task_scores in task_scores_by_agent.items()
        }
        percentiles = PercentileCalculator.compute_percentile_ranks(average_scores)
        ranked_agents = sorted(
            average_scores.items(),
            key=lambda item: item[1],
            reverse=True,
        )
        entries = [
            BundleRankingEntry(
                rank=rank,
                agent_name=agent_name,
                average_score=round(score, 6),
                percentile=round(percentiles.get(agent_name, 0.0), 2),
                completed_tasks=len(common_task_ids),
                total_tasks=len(common_task_ids),
            )
            for rank, (agent_name, score) in enumerate(ranked_agents, start=1)
        ]
        return BundleLeaderboardSnapshot(
            bundle_id=bundle_id,
            metric_name=metric_name,
            task_ids=list(common_task_ids),
            entries=entries,
            population_size=len(entries),
        )

    def get_latest_leaderboard(self) -> LeaderboardSnapshot | None:
        """Return the most recent leaderboard snapshot, or None."""
        return self._snapshots[-1] if self._snapshots else None

    def list_leaderboard_history(self, limit: int = 20) -> list[LeaderboardSnapshot]:
        """Return recent leaderboard snapshots, most recent first."""
        return list(reversed(self._snapshots[-limit:]))

    # ------------------------------------------------------------------
    # Agent profiles
    # ------------------------------------------------------------------

    def get_agent_profile(self, agent_name: str) -> AgentProfile | None:
        """Build a comparative profile for a specific agent.

        Returns ``None`` if the agent has no recorded data.

        Parameters
        ----------
        agent_name:
            The agent to profile.

        Returns
        -------
        AgentProfile or None
            The agent's comparative profile.
        """
        if agent_name not in self._ratings and agent_name not in self._population.agent_names:
            return None

        elo = self._ratings.get(agent_name)
        elo_rating = elo.rating if elo else 1500.0
        return self._comparator.build_agent_profile(agent_name, elo_rating=elo_rating)

    # ------------------------------------------------------------------
    # Rating access
    # ------------------------------------------------------------------

    def get_elo_rating(self, agent_name: str) -> EloRating | None:
        """Get the Elo rating record for an agent."""
        return self._ratings.get(agent_name)

    def get_all_ratings(self) -> dict[str, EloRating]:
        """Get all Elo ratings."""
        return dict(self._ratings)

    def get_rating_history(self, agent_name: str) -> list[float]:
        """Get the Elo rating history for an agent."""
        rating = self._ratings.get(agent_name)
        if rating is None:
            return []
        return list(rating.history)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _store_snapshot(self, snapshot: LeaderboardSnapshot) -> None:
        """Store a leaderboard snapshot with bounded retention."""
        self._snapshots.append(snapshot)
        if len(self._snapshots) > _MAX_SNAPSHOTS:
            self._snapshots = self._snapshots[-_MAX_SNAPSHOTS:]

    def _get_bundle_task_scores(
        self,
        bundle_id: str,
        metric_name: str,
    ) -> dict[str, dict[str, float]]:
        prefix = f"{bundle_id}{_BUNDLE_TASK_SEPARATOR}"
        task_scores_by_agent: dict[str, dict[str, float]] = {}
        for agent_name in sorted(self._population.agent_names):
            task_scores = self._population.get_latest_task_scores(agent_name, metric_name)
            bundle_scores = {
                task_id[len(prefix) :]: value
                for task_id, value in task_scores.items()
                if task_id.startswith(prefix)
            }
            if bundle_scores:
                task_scores_by_agent[agent_name] = bundle_scores
        return task_scores_by_agent

    @staticmethod
    def _get_common_bundle_task_ids(
        task_scores_by_agent: dict[str, dict[str, float]],
    ) -> list[str]:
        task_sets = [
            set(task_scores) for task_scores in task_scores_by_agent.values() if task_scores
        ]
        if not task_sets:
            return []
        return sorted(set.intersection(*task_sets))
