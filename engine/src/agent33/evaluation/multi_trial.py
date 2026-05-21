"""Multi-trial evaluation models and executor.

Implements the multi-trial evaluation pattern from SkillsBench: each
task/agent/model combination is run N times (default 5) and results are
aggregated with binary reward (all-or-nothing) scoring.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field

logger = logging.getLogger(__name__)


class TrialResult(BaseModel):
    """Result of a single evaluation trial."""

    trial_number: int  # 1-indexed
    score: Literal[0, 1]  # binary reward
    duration_ms: int
    error_message: str | None = None
    tokens_used: int = 0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MultiTrialResult(BaseModel):
    """Aggregated results across multiple trials of the same configuration."""

    task_id: str
    agent: str
    model: str
    skills_enabled: bool
    trials: list[TrialResult]
    total_tokens: int = 0
    total_duration_ms: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def pass_rate(self) -> float:
        """Fraction of trials that passed (0.0 to 1.0)."""
        if not self.trials:
            return 0.0
        return sum(t.score for t in self.trials) / len(self.trials)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def variance(self) -> float:
        """Population variance of trial scores."""
        if not self.trials:
            return 0.0
        pr = self.pass_rate
        return sum((t.score - pr) ** 2 for t in self.trials) / len(self.trials)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def std_dev(self) -> float:
        """Population standard deviation of trial scores."""
        result: float = self.variance**0.5
        return result


class SkillsImpact(BaseModel):
    """Measures the impact of skills on task performance.

    skills_impact = pass_rate_with_skills - pass_rate_without_skills
    Positive values indicate skills help; negative values indicate they hurt.
    """

    task_id: str
    agent: str
    model: str
    pass_rate_with_skills: float
    pass_rate_without_skills: float

    @computed_field  # type: ignore[prop-decorator]
    @property
    def skills_impact(self) -> float:
        """Delta between pass rates with and without skills."""
        return self.pass_rate_with_skills - self.pass_rate_without_skills

    @computed_field  # type: ignore[prop-decorator]
    @property
    def confidence(self) -> float:
        """Heuristic confidence score (0..1).

        Higher when the absolute impact is small (less noisy).
        """
        return max(0.0, min(1.0, 1.0 - abs(self.skills_impact) * 0.1))


class ExperimentConfig(BaseModel):
    """Configuration for a multi-trial experiment."""

    tasks: list[str]
    agents: list[str]
    models: list[str]
    trials_per_combination: int = Field(default=5, ge=1, le=100)
    skills_modes: list[bool] = Field(default_factory=lambda: [True, False])
    timeout_per_trial_seconds: int = Field(default=300, ge=1)
    parallel_trials: int = Field(default=1, ge=1)


class MultiTrialRun(BaseModel):
    """A complete multi-trial experiment run."""

    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    config: ExperimentConfig
    results: list[MultiTrialResult] = Field(default_factory=list)
    skills_impacts: list[SkillsImpact] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    status: Literal["pending", "running", "completed", "failed", "cancelled"] = "pending"


# Type alias for the evaluation callback
EvaluationFn = Callable[[str, str, str, bool], Coroutine[Any, Any, bool]]


class MultiTrialExecutor:
    """Executes multi-trial evaluations.

    The evaluation function is an async callable with the signature:
        (task_id, agent, model, skills_enabled) -> bool
    It should return True for pass, False for fail.
    """

    def __init__(
        self,
        evaluation_fn: EvaluationFn | None = None,
        timeout_seconds: int = 300,
    ) -> None:
        self._evaluation_fn = evaluation_fn
        self._timeout = timeout_seconds

    async def execute_trial(
        self,
        task_id: str,
        agent: str,
        model: str,
        skills_enabled: bool,
        trial_number: int,
    ) -> TrialResult:
        """Execute a single trial and return the result."""
        start = time.monotonic()
        if self._evaluation_fn is None:
            duration = int((time.monotonic() - start) * 1000)
            error_msg = "No evaluation function configured"
            logger.warning(
                "trial_failed task=%s agent=%s trial=%d error=%s",
                task_id,
                agent,
                trial_number,
                error_msg,
            )
            return TrialResult(
                trial_number=trial_number,
                score=0,
                duration_ms=duration,
                error_message=error_msg,
            )
        try:
            success = await asyncio.wait_for(
                self._evaluation_fn(task_id, agent, model, skills_enabled),
                timeout=self._timeout,
            )
            duration = int((time.monotonic() - start) * 1000)
            return TrialResult(
                trial_number=trial_number,
                score=1 if success else 0,
                duration_ms=duration,
            )
        except TimeoutError:
            duration = int((time.monotonic() - start) * 1000)
            error_msg = f"Trial timed out after {self._timeout}s"
            logger.warning(
                "trial_failed task=%s agent=%s trial=%d error=%s",
                task_id,
                agent,
                trial_number,
                error_msg,
            )
            return TrialResult(
                trial_number=trial_number,
                score=0,
                duration_ms=duration,
                error_message=error_msg,
            )
        except Exception as exc:
            duration = int((time.monotonic() - start) * 1000)
            logger.warning(
                "trial_failed task=%s agent=%s trial=%d error=%s",
                task_id,
                agent,
                trial_number,
                str(exc),
            )
            return TrialResult(
                trial_number=trial_number,
                score=0,
                duration_ms=duration,
                error_message=str(exc),
            )

    async def execute_multi_trial(
        self,
        task_id: str,
        agent: str,
        model: str,
        skills_enabled: bool,
        num_trials: int = 5,
    ) -> MultiTrialResult:
        """Execute multiple trials for a single configuration."""
        trials: list[TrialResult] = []
        for i in range(1, num_trials + 1):
            trial = await self.execute_trial(task_id, agent, model, skills_enabled, i)
            trials.append(trial)
        return MultiTrialResult(
            task_id=task_id,
            agent=agent,
            model=model,
            skills_enabled=skills_enabled,
            trials=trials,
            total_tokens=sum(t.tokens_used for t in trials),
            total_duration_ms=sum(t.duration_ms for t in trials),
        )

    @staticmethod
    def compute_skills_impact(
        with_skills: MultiTrialResult,
        without_skills: MultiTrialResult,
    ) -> SkillsImpact:
        """Compute skills impact by comparing with/without results."""
        return SkillsImpact(
            task_id=with_skills.task_id,
            agent=with_skills.agent,
            model=with_skills.model,
            pass_rate_with_skills=with_skills.pass_rate,
            pass_rate_without_skills=without_skills.pass_rate,
        )
