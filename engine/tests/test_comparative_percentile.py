"""Tests for percentile calculator."""

from __future__ import annotations

import pytest

from agent33.evaluation.comparative.percentile import PercentileCalculator


class TestComputePercentile:
    def test_empty_population(self) -> None:
        assert PercentileCalculator.compute_percentile(50.0, []) == 0.0

    def test_single_element(self) -> None:
        """Single-element population always returns 50th percentile."""
        assert PercentileCalculator.compute_percentile(42.0, [42.0]) == 50.0

    def test_highest_value(self) -> None:
        """Highest value should be at 100th percentile."""
        pop = [10.0, 20.0, 30.0, 40.0, 50.0]
        assert PercentileCalculator.compute_percentile(50.0, pop) == 100.0

    def test_lowest_value(self) -> None:
        """Lowest value: 1 out of 5 values is <= 10, so 20th percentile."""
        pop = [10.0, 20.0, 30.0, 40.0, 50.0]
        assert PercentileCalculator.compute_percentile(10.0, pop) == 20.0

    def test_median_value(self) -> None:
        pop = [10.0, 20.0, 30.0, 40.0, 50.0]
        result = PercentileCalculator.compute_percentile(30.0, pop)
        assert result == 60.0  # 3 out of 5 are <= 30

    def test_duplicate_values(self) -> None:
        """All same values: all 100th percentile."""
        pop = [50.0, 50.0, 50.0, 50.0]
        assert PercentileCalculator.compute_percentile(50.0, pop) == 100.0


class TestComputePercentileRanks:
    def test_empty_dict(self) -> None:
        assert PercentileCalculator.compute_percentile_ranks({}) == {}

    def test_single_agent(self) -> None:
        ranks = PercentileCalculator.compute_percentile_ranks({"a": 80.0})
        assert ranks["a"] == 50.0  # single element -> 50th

    def test_three_agents(self) -> None:
        scores = {"low": 10.0, "mid": 50.0, "high": 90.0}
        ranks = PercentileCalculator.compute_percentile_ranks(scores)
        # low: 1/3 = 33.33, mid: 2/3 = 66.67, high: 3/3 = 100.0
        assert ranks["high"] > ranks["mid"] > ranks["low"]
        assert abs(ranks["high"] - 100.0) < 0.01

    def test_tied_agents(self) -> None:
        scores = {"a": 50.0, "b": 50.0}
        ranks = PercentileCalculator.compute_percentile_ranks(scores)
        assert ranks["a"] == ranks["b"]
        assert ranks["a"] == 100.0  # both <= 50, 2/2 = 100%


class TestComputeQuantile:
    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            PercentileCalculator.compute_quantile([], 0.5)

    def test_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="Quantile must be"):
            PercentileCalculator.compute_quantile([1.0], 1.5)

    def test_single_value(self) -> None:
        assert PercentileCalculator.compute_quantile([42.0], 0.5) == 42.0

    def test_median_odd_count(self) -> None:
        result = PercentileCalculator.compute_quantile([1.0, 2.0, 3.0], 0.5)
        assert result == 2.0

    def test_median_even_count(self) -> None:
        result = PercentileCalculator.compute_quantile([1.0, 2.0, 3.0, 4.0], 0.5)
        assert result == 2.5

    def test_p25(self) -> None:
        pop = [10.0, 20.0, 30.0, 40.0, 50.0]
        result = PercentileCalculator.compute_quantile(pop, 0.25)
        assert result == 20.0

    def test_p75(self) -> None:
        pop = [10.0, 20.0, 30.0, 40.0, 50.0]
        result = PercentileCalculator.compute_quantile(pop, 0.75)
        assert result == 40.0


class TestComputePopulationStats:
    def test_empty_values(self) -> None:
        result = PercentileCalculator.compute_population_stats("test", [])
        assert result["count"] == 0.0
        assert result["mean"] == 0.0

    def test_single_value(self) -> None:
        result = PercentileCalculator.compute_population_stats("test", [42.0])
        assert result["count"] == 1.0
        assert result["mean"] == 42.0
        assert result["median"] == 42.0
        assert result["std_dev"] == 0.0

    def test_known_stats(self) -> None:
        values = [2.0, 4.0, 6.0, 8.0, 10.0]
        result = PercentileCalculator.compute_population_stats("m", values)
        assert result["count"] == 5.0
        assert result["mean"] == 6.0
        assert result["min"] == 2.0
        assert result["max"] == 10.0
        assert result["median"] == 6.0
        # std_dev for [2,4,6,8,10] (population) = sqrt(8) ~= 2.828
        assert abs(result["std_dev"] - 2.828427) < 0.001
