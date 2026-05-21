"""Pydantic models for comparative evaluation.

Defines the data structures used throughout the group-relative scoring
subsystem: agent scores, population statistics, ranking entries, Elo ratings,
and pairwise comparison results.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class ComparisonOutcome(StrEnum):
    """Outcome of a pairwise comparison between two agents."""

    WIN = "win"
    LOSS = "loss"
    DRAW = "draw"


class AgentScore(BaseModel):
    """A single metric score for an agent on a specific task or overall."""

    agent_name: str
    metric_name: str
    value: float
    task_id: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class BundleRankingEntry(BaseModel):
    """Bundle-scoped aligned ranking entry for one agent."""

    rank: int
    agent_name: str
    average_score: float
    percentile: float = 0.0
    completed_tasks: int = 0
    total_tasks: int = 0


class BundleLeaderboardSnapshot(BaseModel):
    """Leaderboard snapshot for one metric over one persisted synthetic bundle."""

    snapshot_id: str = Field(default_factory=lambda: _new_id("BLB"))
    bundle_id: str
    metric_name: str
    task_ids: list[str] = Field(default_factory=list)
    entries: list[BundleRankingEntry] = Field(default_factory=list)
    population_size: int = 0
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PopulationStats(BaseModel):
    """Descriptive statistics for a metric across a population of agents."""

    metric_name: str
    count: int = 0
    mean: float = 0.0
    std_dev: float = 0.0
    min_value: float = 0.0
    max_value: float = 0.0
    median: float = 0.0
    p25: float = 0.0
    p75: float = 0.0

    @property
    def iqr(self) -> float:
        """Interquartile range."""
        return self.p75 - self.p25


class RankingEntry(BaseModel):
    """An entry in the agent leaderboard."""

    rank: int
    agent_name: str
    elo_rating: float = 1500.0
    percentile: float = 0.0
    total_evaluations: int = 0
    win_count: int = 0
    loss_count: int = 0
    draw_count: int = 0


class EloRating(BaseModel):
    """Elo rating for an agent, tracked over time."""

    agent_name: str
    rating: float = 1500.0
    games_played: int = 0
    win_count: int = 0
    loss_count: int = 0
    draw_count: int = 0
    peak_rating: float = 1500.0
    last_updated: datetime = Field(default_factory=lambda: datetime.now(UTC))
    history: list[float] = Field(default_factory=lambda: [1500.0])

    @property
    def win_rate(self) -> float:
        """Win rate as a fraction of games played."""
        if self.games_played == 0:
            return 0.0
        return self.win_count / self.games_played


class ComparisonResult(BaseModel):
    """Result of a pairwise comparison between two agents."""

    comparison_id: str = Field(default_factory=lambda: _new_id("CMP"))
    agent_a: str
    agent_b: str
    metric_name: str
    score_a: float
    score_b: float
    outcome: ComparisonOutcome
    margin: float = 0.0
    statistically_significant: bool = False
    p_value: float | None = None
    confidence_level: float = 0.95
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentProfile(BaseModel):
    """Comprehensive comparative profile for an agent."""

    agent_name: str
    elo_rating: float = 1500.0
    overall_percentile: float = 0.0
    total_evaluations: int = 0
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    metric_percentiles: dict[str, float] = Field(default_factory=dict)
    recent_trend: str = "stable"  # "improving" | "declining" | "stable"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class LeaderboardSnapshot(BaseModel):
    """A snapshot of the full agent leaderboard."""

    snapshot_id: str = Field(default_factory=lambda: _new_id("LB"))
    entries: list[RankingEntry] = Field(default_factory=list)
    population_size: int = 0
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
