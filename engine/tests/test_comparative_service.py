"""Tests for the comparative evaluation service."""

from __future__ import annotations

from agent33.evaluation.comparative.models import AgentScore, ComparisonOutcome
from agent33.evaluation.comparative.service import ComparativeEvaluationService


def _populate(svc: ComparativeEvaluationService) -> None:
    """Helper to populate with 3 agents across 2 metrics."""
    svc.record_scores(
        [
            AgentScore(agent_name="alpha", metric_name="M-01", value=90.0),
            AgentScore(agent_name="beta", metric_name="M-01", value=70.0),
            AgentScore(agent_name="gamma", metric_name="M-01", value=50.0),
            AgentScore(agent_name="alpha", metric_name="M-02", value=60.0),
            AgentScore(agent_name="beta", metric_name="M-02", value=80.0),
            AgentScore(agent_name="gamma", metric_name="M-02", value=40.0),
        ]
    )


class TestRecordScores:
    def test_records_and_creates_ratings(self) -> None:
        svc = ComparativeEvaluationService()
        svc.record_scores([AgentScore(agent_name="a", metric_name="M-01", value=80.0)])
        assert svc.population_tracker.population_size == 1
        assert svc.get_elo_rating("a") is not None

    def test_multiple_agents(self) -> None:
        svc = ComparativeEvaluationService()
        _populate(svc)
        assert svc.population_tracker.population_size == 3


class TestRunPairwiseEvaluation:
    def test_returns_result_and_updates_elo(self) -> None:
        svc = ComparativeEvaluationService()
        _populate(svc)
        result = svc.run_pairwise_evaluation("alpha", "beta", "M-01")
        assert result is not None
        assert result.outcome == ComparisonOutcome.WIN
        # Elo should have been updated
        alpha_elo = svc.get_elo_rating("alpha")
        assert alpha_elo is not None
        assert alpha_elo.games_played == 1

    def test_returns_none_for_missing_data(self) -> None:
        svc = ComparativeEvaluationService()
        result = svc.run_pairwise_evaluation("x", "y", "M-01")
        assert result is None


class TestRunRoundRobin:
    def test_all_pairs_compared(self) -> None:
        svc = ComparativeEvaluationService()
        _populate(svc)
        results = svc.run_round_robin("M-01")
        # 3 agents -> 3 choose 2 = 3 pairs
        assert len(results) == 3

    def test_insufficient_population(self) -> None:
        svc = ComparativeEvaluationService(min_population_size=5)
        _populate(svc)
        results = svc.run_round_robin("M-01")
        assert len(results) == 0


class TestGenerateLeaderboard:
    def test_leaderboard_after_round_robin(self) -> None:
        svc = ComparativeEvaluationService()
        _populate(svc)
        svc.run_round_robin("M-01")
        lb = svc.generate_leaderboard()
        assert lb.population_size == 3
        assert len(lb.entries) == 3
        # Alpha should be ranked #1 (highest M-01 score -> wins both matchups)
        assert lb.entries[0].agent_name == "alpha"
        assert lb.entries[0].rank == 1

    def test_empty_leaderboard(self) -> None:
        svc = ComparativeEvaluationService()
        lb = svc.generate_leaderboard()
        assert lb.population_size == 0

    def test_snapshot_stored(self) -> None:
        svc = ComparativeEvaluationService()
        _populate(svc)
        svc.generate_leaderboard()
        assert svc.get_latest_leaderboard() is not None


class TestGetAgentProfile:
    def test_profile_with_data(self) -> None:
        svc = ComparativeEvaluationService()
        _populate(svc)
        profile = svc.get_agent_profile("alpha")
        assert profile is not None
        assert profile.agent_name == "alpha"
        assert "M-01" in profile.metric_percentiles

    def test_profile_unknown_agent_returns_none(self) -> None:
        svc = ComparativeEvaluationService()
        assert svc.get_agent_profile("nonexistent") is None


class TestRatingHistory:
    def test_history_tracking(self) -> None:
        svc = ComparativeEvaluationService()
        _populate(svc)
        svc.run_round_robin("M-01")
        history = svc.get_rating_history("alpha")
        # Initial (1500) + games played
        assert len(history) > 1

    def test_no_history_for_unknown(self) -> None:
        svc = ComparativeEvaluationService()
        assert svc.get_rating_history("ghost") == []
