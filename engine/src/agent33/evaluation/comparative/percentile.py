"""Percentile calculator for agent population ranking.

Computes percentile ranks across an agent population for each metric,
supporting small populations gracefully with interpolated percentiles.
"""

from __future__ import annotations

import math


class PercentileCalculator:
    """Compute percentile ranks for agents within a population.

    Uses linear interpolation for percentile computation, which handles
    small populations more gracefully than simple rank-based methods.
    """

    @staticmethod
    def compute_percentile(value: float, population: list[float]) -> float:
        """Compute the percentile rank of a value within a population.

        Returns the percentage of values in the population that are less than
        or equal to the given value, using the "weak" (less-than-or-equal)
        definition.

        Parameters
        ----------
        value:
            The value to rank.
        population:
            The full population of values (must include ``value`` itself).

        Returns
        -------
        float
            Percentile rank in range [0.0, 100.0].
        """
        if not population:
            return 0.0
        n = len(population)
        if n == 1:
            return 50.0
        count_below_or_equal = sum(1 for v in population if v <= value)
        return (count_below_or_equal / n) * 100.0

    @staticmethod
    def compute_percentile_ranks(
        agent_scores: dict[str, float],
    ) -> dict[str, float]:
        """Compute percentile ranks for all agents in a population.

        Parameters
        ----------
        agent_scores:
            Mapping of agent name to score value. Higher scores are better.

        Returns
        -------
        dict[str, float]
            Mapping of agent name to percentile rank (0.0 to 100.0).
        """
        if not agent_scores:
            return {}
        population = list(agent_scores.values())
        return {
            agent: PercentileCalculator.compute_percentile(score, population)
            for agent, score in agent_scores.items()
        }

    @staticmethod
    def compute_quantile(population: list[float], q: float) -> float:
        """Compute a specific quantile from a population using linear interpolation.

        Parameters
        ----------
        population:
            The population values. Must not be empty.
        q:
            Quantile to compute, in range [0.0, 1.0].

        Returns
        -------
        float
            The interpolated quantile value.

        Raises
        ------
        ValueError
            If population is empty or q is out of range.
        """
        if not population:
            raise ValueError("Cannot compute quantile of empty population")
        if not 0.0 <= q <= 1.0:
            raise ValueError(f"Quantile must be in [0, 1], got {q}")
        sorted_pop = sorted(population)
        n = len(sorted_pop)
        if n == 1:
            return sorted_pop[0]
        # Linear interpolation
        pos = q * (n - 1)
        lower = int(math.floor(pos))
        upper = min(lower + 1, n - 1)
        frac = pos - lower
        return sorted_pop[lower] + frac * (sorted_pop[upper] - sorted_pop[lower])

    @staticmethod
    def compute_population_stats(
        metric_name: str,
        values: list[float],
    ) -> dict[str, float]:
        """Compute descriptive statistics for a population of values.

        Returns a dict with keys: count, mean, std_dev, min, max, median,
        p25, p75.

        Parameters
        ----------
        metric_name:
            Name of the metric (included in the returned dict).
        values:
            Population values.
        """
        if not values:
            return {
                "metric_name": 0.0,
                "count": 0.0,
                "mean": 0.0,
                "std_dev": 0.0,
                "min": 0.0,
                "max": 0.0,
                "median": 0.0,
                "p25": 0.0,
                "p75": 0.0,
            }
        n = len(values)
        mean = sum(values) / n
        variance = sum((v - mean) ** 2 for v in values) / n
        std_dev = variance**0.5
        calc = PercentileCalculator
        return {
            "metric_name": metric_name,
            "count": float(n),
            "mean": round(mean, 6),
            "std_dev": round(std_dev, 6),
            "min": min(values),
            "max": max(values),
            "median": calc.compute_quantile(values, 0.5),
            "p25": calc.compute_quantile(values, 0.25),
            "p75": calc.compute_quantile(values, 0.75),
        }
