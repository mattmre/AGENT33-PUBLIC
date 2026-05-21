"""Tests for population tracker."""

from __future__ import annotations

from agent33.evaluation.comparative.models import AgentScore
from agent33.evaluation.comparative.population import PopulationTracker


class TestAddScore:
    def test_single_score(self) -> None:
        tracker = PopulationTracker()
        tracker.add_score(AgentScore(agent_name="a", metric_name="M-01", value=80.0))
        assert tracker.population_size == 1
        assert "M-01" in tracker.metric_names

    def test_multiple_agents(self) -> None:
        tracker = PopulationTracker()
        tracker.add_score(AgentScore(agent_name="a", metric_name="M-01", value=80.0))
        tracker.add_score(AgentScore(agent_name="b", metric_name="M-01", value=70.0))
        assert tracker.population_size == 2

    def test_bounded_retention(self) -> None:
        tracker = PopulationTracker(max_scores_per_agent_metric=3)
        for i in range(10):
            tracker.add_score(AgentScore(agent_name="a", metric_name="M-01", value=float(i)))
        # Only last 3 should be retained
        scores = tracker._scores["M-01"]["a"]
        assert len(scores) == 3
        assert scores == [7.0, 8.0, 9.0]


class TestAddScores:
    def test_batch_add(self) -> None:
        tracker = PopulationTracker()
        scores = [
            AgentScore(agent_name="a", metric_name="M-01", value=80.0),
            AgentScore(agent_name="b", metric_name="M-01", value=70.0),
            AgentScore(agent_name="a", metric_name="M-02", value=90.0),
        ]
        tracker.add_scores(scores)
        assert tracker.population_size == 2
        assert len(tracker.metric_names) == 2


class TestGetAgentMean:
    def test_no_data_returns_none(self) -> None:
        tracker = PopulationTracker()
        assert tracker.get_agent_mean("a", "M-01") is None

    def test_computes_mean(self) -> None:
        tracker = PopulationTracker()
        tracker.add_score(AgentScore(agent_name="a", metric_name="M-01", value=80.0))
        tracker.add_score(AgentScore(agent_name="a", metric_name="M-01", value=90.0))
        mean = tracker.get_agent_mean("a", "M-01")
        assert mean is not None
        assert abs(mean - 85.0) < 1e-6


class TestGetAgentLatest:
    def test_no_data_returns_none(self) -> None:
        tracker = PopulationTracker()
        assert tracker.get_agent_latest("a", "M-01") is None

    def test_returns_latest(self) -> None:
        tracker = PopulationTracker()
        tracker.add_score(AgentScore(agent_name="a", metric_name="M-01", value=80.0))
        tracker.add_score(AgentScore(agent_name="a", metric_name="M-01", value=95.0))
        assert tracker.get_agent_latest("a", "M-01") == 95.0


class TestGetPopulationMeans:
    def test_empty(self) -> None:
        tracker = PopulationTracker()
        assert tracker.get_population_means("M-01") == {}

    def test_multiple_agents(self) -> None:
        tracker = PopulationTracker()
        tracker.add_score(AgentScore(agent_name="a", metric_name="M-01", value=80.0))
        tracker.add_score(AgentScore(agent_name="a", metric_name="M-01", value=100.0))
        tracker.add_score(AgentScore(agent_name="b", metric_name="M-01", value=60.0))
        means = tracker.get_population_means("M-01")
        assert abs(means["a"] - 90.0) < 1e-6
        assert abs(means["b"] - 60.0) < 1e-6


class TestComputeStats:
    def test_empty_metric(self) -> None:
        tracker = PopulationTracker()
        stats = tracker.compute_stats("M-01")
        assert stats.count == 0
        assert stats.mean == 0.0

    def test_stats_values(self) -> None:
        tracker = PopulationTracker()
        # Add single scores per agent so mean = the value
        for name, val in [("a", 10.0), ("b", 20.0), ("c", 30.0)]:
            tracker.add_score(AgentScore(agent_name=name, metric_name="M-01", value=val))
        stats = tracker.compute_stats("M-01")
        assert stats.count == 3
        assert abs(stats.mean - 20.0) < 0.01
        assert stats.min_value == 10.0
        assert stats.max_value == 30.0


class TestClear:
    def test_clear_removes_all(self) -> None:
        tracker = PopulationTracker()
        tracker.add_score(AgentScore(agent_name="a", metric_name="M-01", value=80.0))
        assert tracker.population_size == 1
        tracker.clear()
        assert tracker.population_size == 0
        assert len(tracker.metric_names) == 0


class TestAgentScoresCount:
    def test_count_across_metrics(self) -> None:
        tracker = PopulationTracker()
        tracker.add_score(AgentScore(agent_name="a", metric_name="M-01", value=80.0))
        tracker.add_score(AgentScore(agent_name="a", metric_name="M-02", value=90.0))
        tracker.add_score(AgentScore(agent_name="a", metric_name="M-01", value=85.0))
        assert tracker.get_agent_scores_count("a") == 3
        assert tracker.get_agent_scores_count("b") == 0
