"""Tests for agent comparator."""

from __future__ import annotations

from agent33.evaluation.comparative.comparator import AgentComparator
from agent33.evaluation.comparative.models import AgentScore, ComparisonOutcome
from agent33.evaluation.comparative.population import PopulationTracker


def _make_tracker(*agent_scores: tuple[str, str, float]) -> PopulationTracker:
    """Helper to build a populated tracker."""
    tracker = PopulationTracker()
    for agent, metric, value in agent_scores:
        tracker.add_score(AgentScore(agent_name=agent, metric_name=metric, value=value))
    return tracker


class TestCompareAgents:
    def test_missing_data_returns_none(self) -> None:
        tracker = _make_tracker(("a", "M-01", 80.0))
        comp = AgentComparator(tracker)
        result = comp.compare_agents("a", "b", "M-01")
        assert result is None

    def test_win_when_a_higher(self) -> None:
        tracker = _make_tracker(("a", "M-01", 90.0), ("b", "M-01", 70.0))
        comp = AgentComparator(tracker)
        result = comp.compare_agents("a", "b", "M-01")
        assert result is not None
        assert result.outcome == ComparisonOutcome.WIN
        assert result.margin > 0

    def test_loss_when_a_lower(self) -> None:
        tracker = _make_tracker(("a", "M-01", 40.0), ("b", "M-01", 80.0))
        comp = AgentComparator(tracker)
        result = comp.compare_agents("a", "b", "M-01")
        assert result is not None
        assert result.outcome == ComparisonOutcome.LOSS

    def test_draw_within_threshold(self) -> None:
        tracker = _make_tracker(("a", "M-01", 50.005), ("b", "M-01", 50.0))
        comp = AgentComparator(tracker, draw_threshold=0.01)
        result = comp.compare_agents("a", "b", "M-01")
        assert result is not None
        assert result.outcome == ComparisonOutcome.DRAW

    def test_custom_draw_threshold(self) -> None:
        tracker = _make_tracker(("a", "M-01", 51.0), ("b", "M-01", 50.0))
        comp = AgentComparator(tracker, draw_threshold=2.0)
        result = comp.compare_agents("a", "b", "M-01")
        assert result is not None
        assert result.outcome == ComparisonOutcome.DRAW


class TestCompareAllMetrics:
    def test_multiple_metrics(self) -> None:
        tracker = _make_tracker(
            ("a", "M-01", 90.0),
            ("b", "M-01", 70.0),
            ("a", "M-02", 50.0),
            ("b", "M-02", 80.0),
        )
        comp = AgentComparator(tracker)
        results = comp.compare_all_metrics("a", "b")
        assert len(results) == 2
        # a wins M-01, b wins M-02
        outcomes = {r.metric_name: r.outcome for r in results}
        assert outcomes["M-01"] == ComparisonOutcome.WIN
        assert outcomes["M-02"] == ComparisonOutcome.LOSS

    def test_partial_data(self) -> None:
        """Only returns comparisons where both agents have data."""
        tracker = _make_tracker(
            ("a", "M-01", 90.0),
            ("b", "M-01", 70.0),
            ("a", "M-02", 50.0),
            # b has no M-02 data
        )
        comp = AgentComparator(tracker)
        results = comp.compare_all_metrics("a", "b")
        assert len(results) == 1
        assert results[0].metric_name == "M-01"


class TestBuildAgentProfile:
    def test_basic_profile(self) -> None:
        tracker = _make_tracker(
            ("a", "M-01", 90.0),
            ("b", "M-01", 50.0),
            ("c", "M-01", 30.0),
        )
        comp = AgentComparator(tracker)
        profile = comp.build_agent_profile("a", elo_rating=1600.0)
        assert profile.agent_name == "a"
        assert profile.elo_rating == 1600.0
        assert "M-01" in profile.metric_percentiles
        # a has highest score, should be at high percentile
        assert profile.metric_percentiles["M-01"] == 100.0

    def test_strengths_and_weaknesses(self) -> None:
        # Need 5+ agents so the lowest percentile (1/5 = 20%) falls below
        # the WEAKNESS_THRESHOLD (25%) and highest (5/5 = 100%) is above
        # STRENGTH_THRESHOLD (75%).
        tracker = _make_tracker(
            ("agent", "speed", 99.0),
            ("agent", "accuracy", 5.0),
            ("b", "speed", 50.0),
            ("b", "accuracy", 50.0),
            ("c", "speed", 40.0),
            ("c", "accuracy", 60.0),
            ("d", "speed", 30.0),
            ("d", "accuracy", 70.0),
            ("e", "speed", 20.0),
            ("e", "accuracy", 90.0),
        )
        comp = AgentComparator(tracker)
        profile = comp.build_agent_profile("agent")
        # agent is best at speed (100th pct -> strength), worst at accuracy (20th pct -> weakness)
        assert "speed" in profile.strengths
        assert "accuracy" in profile.weaknesses

    def test_no_data_returns_empty_profile(self) -> None:
        tracker = PopulationTracker()
        comp = AgentComparator(tracker)
        profile = comp.build_agent_profile("ghost")
        assert profile.total_evaluations == 0
        assert profile.metric_percentiles == {}


class TestStatisticalSignificance:
    def test_significance_with_multiple_samples(self) -> None:
        """Multiple very different samples should yield significant result."""
        tracker = PopulationTracker()
        for _ in range(20):
            tracker.add_score(AgentScore(agent_name="strong", metric_name="M-01", value=95.0))
            tracker.add_score(AgentScore(agent_name="weak", metric_name="M-01", value=10.0))
        comp = AgentComparator(tracker, confidence_level=0.95)
        result = comp.compare_agents("strong", "weak", "M-01")
        assert result is not None
        assert result.p_value is not None
        assert result.p_value < 0.05
        assert result.statistically_significant is True

    def test_insufficient_samples_no_p_value(self) -> None:
        """Single sample per agent yields no p-value."""
        tracker = _make_tracker(("a", "M-01", 90.0), ("b", "M-01", 70.0))
        comp = AgentComparator(tracker)
        result = comp.compare_agents("a", "b", "M-01")
        assert result is not None
        assert result.p_value is None
        assert result.statistically_significant is False
