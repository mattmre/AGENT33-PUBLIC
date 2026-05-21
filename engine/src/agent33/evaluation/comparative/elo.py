"""Elo rating system adapted for agent evaluation.

Implements a standard Elo rating system with configurable K-factor,
adapted for comparing agents based on evaluation metrics rather than
head-to-head games. Handles edge cases: new agents with no history,
draws, and statistical ties.
"""

from __future__ import annotations

import math

from agent33.evaluation.comparative.models import ComparisonOutcome, EloRating

# Default starting rating for new agents
DEFAULT_RATING = 1500.0

# Default K-factor: controls how much ratings change per game.
# Higher K = more volatile; lower K = more stable.
DEFAULT_K_FACTOR = 32.0

# Minimum K-factor for experienced agents (games > provisional_threshold)
MIN_K_FACTOR = 16.0

# Number of games below which an agent is considered "provisional"
# and uses the full K-factor for faster convergence.
PROVISIONAL_THRESHOLD = 30


class EloCalculator:
    """Elo rating calculator for agent evaluation comparisons.

    Supports adaptive K-factor (higher for new agents, lower for
    established ones), draw handling, and rating history tracking.
    """

    def __init__(
        self,
        k_factor: float = DEFAULT_K_FACTOR,
        min_k_factor: float = MIN_K_FACTOR,
        provisional_threshold: int = PROVISIONAL_THRESHOLD,
        default_rating: float = DEFAULT_RATING,
    ) -> None:
        self._k_factor = k_factor
        self._min_k_factor = min_k_factor
        self._provisional_threshold = provisional_threshold
        self._default_rating = default_rating

    @property
    def default_rating(self) -> float:
        return self._default_rating

    def expected_score(self, rating_a: float, rating_b: float) -> float:
        """Compute the expected score for player A against player B.

        Uses the standard Elo expected score formula:
            E_A = 1 / (1 + 10^((R_B - R_A) / 400))

        Parameters
        ----------
        rating_a:
            Current rating of player A.
        rating_b:
            Current rating of player B.

        Returns
        -------
        float
            Expected score for A in range (0.0, 1.0).
        """
        exponent = (rating_b - rating_a) / 400.0
        return 1.0 / (1.0 + math.pow(10.0, exponent))

    def effective_k_factor(self, games_played: int) -> float:
        """Compute the effective K-factor based on experience.

        Provisional agents (below the threshold) use the full K-factor
        for faster convergence. Experienced agents use the minimum
        K-factor for stability.

        Parameters
        ----------
        games_played:
            Number of games the agent has played.

        Returns
        -------
        float
            Effective K-factor.
        """
        if games_played < self._provisional_threshold:
            return self._k_factor
        return self._min_k_factor

    def update_ratings(
        self,
        rating_a: EloRating,
        rating_b: EloRating,
        outcome: ComparisonOutcome,
    ) -> tuple[float, float]:
        """Update Elo ratings after a comparison.

        Mutates both ``rating_a`` and ``rating_b`` in place and returns
        the new rating values.

        Parameters
        ----------
        rating_a:
            Rating record for agent A (the "reference" agent).
        rating_b:
            Rating record for agent B (the "opponent" agent).
        outcome:
            The outcome from agent A's perspective (WIN/LOSS/DRAW).

        Returns
        -------
        tuple[float, float]
            New ratings for (agent A, agent B).
        """
        # Actual scores: 1.0 for win, 0.0 for loss, 0.5 for draw
        if outcome == ComparisonOutcome.WIN:
            actual_a = 1.0
            actual_b = 0.0
        elif outcome == ComparisonOutcome.LOSS:
            actual_a = 0.0
            actual_b = 1.0
        else:
            actual_a = 0.5
            actual_b = 0.5

        expected_a = self.expected_score(rating_a.rating, rating_b.rating)
        expected_b = 1.0 - expected_a

        k_a = self.effective_k_factor(rating_a.games_played)
        k_b = self.effective_k_factor(rating_b.games_played)

        new_rating_a = rating_a.rating + k_a * (actual_a - expected_a)
        new_rating_b = rating_b.rating + k_b * (actual_b - expected_b)

        # Update rating_a
        rating_a.rating = round(new_rating_a, 2)
        rating_a.games_played += 1
        rating_a.peak_rating = max(rating_a.peak_rating, rating_a.rating)
        rating_a.history.append(rating_a.rating)
        if outcome == ComparisonOutcome.WIN:
            rating_a.win_count += 1
        elif outcome == ComparisonOutcome.LOSS:
            rating_a.loss_count += 1
        else:
            rating_a.draw_count += 1

        # Update rating_b
        rating_b.rating = round(new_rating_b, 2)
        rating_b.games_played += 1
        rating_b.peak_rating = max(rating_b.peak_rating, rating_b.rating)
        rating_b.history.append(rating_b.rating)
        if outcome == ComparisonOutcome.WIN:
            rating_b.loss_count += 1
        elif outcome == ComparisonOutcome.LOSS:
            rating_b.win_count += 1
        else:
            rating_b.draw_count += 1

        return (rating_a.rating, rating_b.rating)

    def create_rating(self, agent_name: str) -> EloRating:
        """Create a new Elo rating for an agent at the default rating."""
        return EloRating(
            agent_name=agent_name,
            rating=self._default_rating,
            peak_rating=self._default_rating,
            history=[self._default_rating],
        )
