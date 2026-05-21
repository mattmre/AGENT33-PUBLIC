"""Tests for the Elo rating system."""

from __future__ import annotations

from agent33.evaluation.comparative.elo import (
    DEFAULT_K_FACTOR,
    DEFAULT_RATING,
    MIN_K_FACTOR,
    PROVISIONAL_THRESHOLD,
    EloCalculator,
)
from agent33.evaluation.comparative.models import ComparisonOutcome, EloRating


class TestExpectedScore:
    def test_equal_ratings(self) -> None:
        calc = EloCalculator()
        expected = calc.expected_score(1500.0, 1500.0)
        assert abs(expected - 0.5) < 1e-6

    def test_higher_a_favored(self) -> None:
        calc = EloCalculator()
        expected = calc.expected_score(1700.0, 1500.0)
        assert expected > 0.5

    def test_lower_a_unfavored(self) -> None:
        calc = EloCalculator()
        expected = calc.expected_score(1300.0, 1500.0)
        assert expected < 0.5

    def test_400_point_difference(self) -> None:
        """400-point Elo difference means ~0.91 expected for the stronger player."""
        calc = EloCalculator()
        expected = calc.expected_score(1900.0, 1500.0)
        assert abs(expected - 0.909) < 0.01

    def test_symmetry(self) -> None:
        """Expected scores for A vs B and B vs A should sum to 1.0."""
        calc = EloCalculator()
        e_a = calc.expected_score(1600.0, 1400.0)
        e_b = calc.expected_score(1400.0, 1600.0)
        assert abs(e_a + e_b - 1.0) < 1e-6


class TestEffectiveKFactor:
    def test_provisional_agent(self) -> None:
        calc = EloCalculator()
        assert calc.effective_k_factor(0) == DEFAULT_K_FACTOR
        assert calc.effective_k_factor(PROVISIONAL_THRESHOLD - 1) == DEFAULT_K_FACTOR

    def test_experienced_agent(self) -> None:
        calc = EloCalculator()
        assert calc.effective_k_factor(PROVISIONAL_THRESHOLD) == MIN_K_FACTOR
        assert calc.effective_k_factor(100) == MIN_K_FACTOR

    def test_custom_k_factors(self) -> None:
        calc = EloCalculator(k_factor=40.0, min_k_factor=20.0, provisional_threshold=10)
        assert calc.effective_k_factor(5) == 40.0
        assert calc.effective_k_factor(10) == 20.0


class TestUpdateRatings:
    def test_win_increases_winner_rating(self) -> None:
        calc = EloCalculator()
        a = calc.create_rating("a")
        b = calc.create_rating("b")
        new_a, new_b = calc.update_ratings(a, b, ComparisonOutcome.WIN)
        assert new_a > DEFAULT_RATING
        assert new_b < DEFAULT_RATING

    def test_loss_decreases_loser_rating(self) -> None:
        calc = EloCalculator()
        a = calc.create_rating("a")
        b = calc.create_rating("b")
        new_a, new_b = calc.update_ratings(a, b, ComparisonOutcome.LOSS)
        assert new_a < DEFAULT_RATING
        assert new_b > DEFAULT_RATING

    def test_draw_minimal_change_equal_ratings(self) -> None:
        """A draw between equal-rated agents should not change ratings."""
        calc = EloCalculator()
        a = calc.create_rating("a")
        b = calc.create_rating("b")
        new_a, new_b = calc.update_ratings(a, b, ComparisonOutcome.DRAW)
        assert abs(new_a - DEFAULT_RATING) < 0.01
        assert abs(new_b - DEFAULT_RATING) < 0.01

    def test_draw_between_unequal_ratings_converges(self) -> None:
        """Draw between unequal agents should pull ratings toward each other."""
        calc = EloCalculator()
        a = EloRating(agent_name="a", rating=1600.0, history=[1600.0])
        b = EloRating(agent_name="b", rating=1400.0, history=[1400.0])
        new_a, new_b = calc.update_ratings(a, b, ComparisonOutcome.DRAW)
        assert new_a < 1600.0  # Higher-rated drawn down
        assert new_b > 1400.0  # Lower-rated pulled up

    def test_games_played_incremented(self) -> None:
        calc = EloCalculator()
        a = calc.create_rating("a")
        b = calc.create_rating("b")
        calc.update_ratings(a, b, ComparisonOutcome.WIN)
        assert a.games_played == 1
        assert b.games_played == 1

    def test_win_count_tracked(self) -> None:
        calc = EloCalculator()
        a = calc.create_rating("a")
        b = calc.create_rating("b")
        calc.update_ratings(a, b, ComparisonOutcome.WIN)
        assert a.win_count == 1
        assert b.loss_count == 1

    def test_history_appended(self) -> None:
        calc = EloCalculator()
        a = calc.create_rating("a")
        b = calc.create_rating("b")
        assert len(a.history) == 1
        calc.update_ratings(a, b, ComparisonOutcome.WIN)
        assert len(a.history) == 2
        assert len(b.history) == 2

    def test_peak_rating_tracked(self) -> None:
        calc = EloCalculator()
        a = calc.create_rating("a")
        b = calc.create_rating("b")
        calc.update_ratings(a, b, ComparisonOutcome.WIN)
        assert a.peak_rating >= DEFAULT_RATING

    def test_convergence_over_many_games(self) -> None:
        """Stronger agent should converge to higher rating over many games."""
        calc = EloCalculator(k_factor=32.0)
        strong = calc.create_rating("strong")
        weak = calc.create_rating("weak")
        # Simulate strong winning 80% of games
        for i in range(100):
            outcome = ComparisonOutcome.WIN if i % 5 != 0 else ComparisonOutcome.LOSS
            calc.update_ratings(strong, weak, outcome)
        assert strong.rating > weak.rating
        assert strong.rating > DEFAULT_RATING
        assert weak.rating < DEFAULT_RATING

    def test_zero_sum(self) -> None:
        """Total rating change should be approximately zero-sum."""
        calc = EloCalculator()
        a = calc.create_rating("a")
        b = calc.create_rating("b")
        initial_total = a.rating + b.rating
        calc.update_ratings(a, b, ComparisonOutcome.WIN)
        # Not perfectly zero-sum when K-factors differ, but same here
        assert abs((a.rating + b.rating) - initial_total) < 0.01


class TestCreateRating:
    def test_default_values(self) -> None:
        calc = EloCalculator()
        rating = calc.create_rating("test-agent")
        assert rating.agent_name == "test-agent"
        assert rating.rating == DEFAULT_RATING
        assert rating.games_played == 0
        assert rating.history == [DEFAULT_RATING]

    def test_custom_default_rating(self) -> None:
        calc = EloCalculator(default_rating=1000.0)
        rating = calc.create_rating("custom")
        assert rating.rating == 1000.0
        assert rating.peak_rating == 1000.0
