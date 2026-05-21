"""Tests for comparative evaluation data models."""

from __future__ import annotations

from agent33.evaluation.comparative.models import (
    AgentScore,
    ComparisonOutcome,
    ComparisonResult,
    EloRating,
    LeaderboardSnapshot,
    PopulationStats,
    RankingEntry,
)


class TestAgentScore:
    def test_create_with_defaults(self) -> None:
        score = AgentScore(agent_name="agent-a", metric_name="M-01", value=85.0)
        assert score.agent_name == "agent-a"
        assert score.metric_name == "M-01"
        assert score.value == 85.0
        assert score.task_id is None
        assert score.timestamp is not None

    def test_create_with_task_id(self) -> None:
        score = AgentScore(agent_name="agent-b", metric_name="M-02", value=42.5, task_id="GT-01")
        assert score.task_id == "GT-01"


class TestPopulationStats:
    def test_iqr_property(self) -> None:
        stats = PopulationStats(metric_name="M-01", p25=25.0, p75=75.0)
        assert stats.iqr == 50.0

    def test_defaults(self) -> None:
        stats = PopulationStats(metric_name="test")
        assert stats.count == 0
        assert stats.mean == 0.0
        assert stats.std_dev == 0.0


class TestEloRating:
    def test_defaults(self) -> None:
        rating = EloRating(agent_name="agent-a")
        assert rating.rating == 1500.0
        assert rating.games_played == 0
        assert rating.peak_rating == 1500.0
        assert rating.history == [1500.0]

    def test_win_rate_no_games(self) -> None:
        rating = EloRating(agent_name="agent-a")
        assert rating.win_rate == 0.0

    def test_win_rate_with_games(self) -> None:
        rating = EloRating(agent_name="agent-a", games_played=10, win_count=7)
        assert rating.win_rate == 0.7


class TestComparisonResult:
    def test_create(self) -> None:
        result = ComparisonResult(
            agent_a="agent-a",
            agent_b="agent-b",
            metric_name="M-01",
            score_a=90.0,
            score_b=80.0,
            outcome=ComparisonOutcome.WIN,
            margin=10.0,
        )
        assert result.outcome == ComparisonOutcome.WIN
        assert result.margin == 10.0
        assert result.comparison_id.startswith("CMP-")

    def test_draw_outcome(self) -> None:
        result = ComparisonResult(
            agent_a="x",
            agent_b="y",
            metric_name="M-01",
            score_a=50.0,
            score_b=50.0,
            outcome=ComparisonOutcome.DRAW,
        )
        assert result.outcome == ComparisonOutcome.DRAW


class TestRankingEntry:
    def test_defaults(self) -> None:
        entry = RankingEntry(rank=1, agent_name="top-agent")
        assert entry.elo_rating == 1500.0
        assert entry.percentile == 0.0


class TestLeaderboardSnapshot:
    def test_snapshot_id_prefix(self) -> None:
        snap = LeaderboardSnapshot()
        assert snap.snapshot_id.startswith("LB-")
        assert snap.population_size == 0
