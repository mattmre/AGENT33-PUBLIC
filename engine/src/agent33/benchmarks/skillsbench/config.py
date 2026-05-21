"""Configuration for SkillsBench benchmark runs."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from agent33.benchmarks.skillsbench.models import TaskFilter


class SkillsBenchConfig(BaseModel):
    """Configuration for a SkillsBench benchmark run.

    Parameters
    ----------
    skillsbench_root:
        Root directory of the SkillsBench repository checkout.
        Must contain a ``tasks/`` subdirectory.
    agent_name:
        Name of the agent definition to use for evaluation.
    model:
        LLM model identifier for the agent runtime.
    trials_per_task:
        Number of trials to run per task (SkillsBench default is 5).
    skills_enabled:
        Whether to load bundled skills from task directories.
    pytest_timeout_seconds:
        Maximum time for each pytest subprocess to complete.
    task_filter:
        Optional filter to select a subset of tasks.
    """

    skillsbench_root: Path = Field(
        default=Path("./skillsbench"),
        description="Root directory of the SkillsBench repository checkout.",
    )
    agent_name: str = Field(
        default="code-worker",
        description="Agent definition name to use for evaluation.",
    )
    model: str = Field(
        default="llama3.2",
        description="LLM model to use for the agent runtime.",
    )
    trials_per_task: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Number of trials per task (SkillsBench default: 5).",
    )
    skills_enabled: bool = Field(
        default=True,
        description="Whether to load bundled task skills.",
    )
    pytest_timeout_seconds: float = Field(
        default=300.0,
        gt=0,
        description="Timeout for each pytest subprocess (seconds).",
    )
    task_filter: TaskFilter = Field(
        default_factory=TaskFilter,
        description="Filter criteria for selecting tasks.",
    )
