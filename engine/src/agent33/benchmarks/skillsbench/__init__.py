"""SkillsBench evaluation adapter package.

Bridges AGENT-33's multi-trial evaluation infrastructure to real
SkillsBench-format tasks using subprocess pytest for binary reward scoring.
"""

from __future__ import annotations

from agent33.benchmarks.skillsbench.adapter import SkillsBenchAdapter
from agent33.benchmarks.skillsbench.config import SkillsBenchConfig
from agent33.benchmarks.skillsbench.models import (
    BenchmarkRunResult,
    BenchmarkRunStatus,
    TaskFilter,
    TrialOutcome,
    TrialRecord,
)
from agent33.benchmarks.skillsbench.regression import (
    SkillsBenchRegressionReport,
    SkillsBenchRegressionThresholds,
    attach_baseline_comparison,
    compare_ctrf_reports,
)
from agent33.benchmarks.skillsbench.runner import PytestBinaryRewardRunner, PytestResult
from agent33.benchmarks.skillsbench.task_loader import SkillsBenchTask, SkillsBenchTaskLoader

__all__ = [
    "BenchmarkRunResult",
    "BenchmarkRunStatus",
    "PytestBinaryRewardRunner",
    "PytestResult",
    "SkillsBenchAdapter",
    "SkillsBenchConfig",
    "SkillsBenchRegressionReport",
    "SkillsBenchRegressionThresholds",
    "SkillsBenchTask",
    "SkillsBenchTaskLoader",
    "TaskFilter",
    "TrialOutcome",
    "TrialRecord",
    "attach_baseline_comparison",
    "compare_ctrf_reports",
]
