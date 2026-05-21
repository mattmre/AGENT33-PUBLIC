"""Tests for SkillsBench adapter bridge."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent33.benchmarks.skillsbench.adapter import SkillsBenchAdapter
from agent33.benchmarks.skillsbench.config import SkillsBenchConfig
from agent33.benchmarks.skillsbench.models import (
    BenchmarkRunStatus,
    TrialOutcome,
)
from agent33.benchmarks.skillsbench.runner import PytestBinaryRewardRunner, PytestResult
from agent33.benchmarks.skillsbench.storage import SkillsBenchArtifactStore
from agent33.benchmarks.skillsbench.task_loader import SkillsBenchTask, SkillsBenchTaskLoader
from agent33.skills.registry import SkillRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_task(
    task_id: str = "math/addition",
    category: str = "math",
    instruction: str = "Add two numbers.",
    skills_dir: Path | None = None,
) -> SkillsBenchTask:
    return SkillsBenchTask(
        task_id=task_id,
        category=category,
        instruction=instruction,
        skills_dir=skills_dir,
        tests_path=Path("/fake/tests/test_outputs.py"),
    )


def _make_iterative_result(
    tokens_used: int = 100,
    iterations: int = 3,
    tool_calls_made: int = 5,
    termination_reason: str = "completed",
) -> MagicMock:
    """Create a mock IterativeAgentResult."""
    mock = MagicMock()
    mock.tokens_used = tokens_used
    mock.iterations = iterations
    mock.tool_calls_made = tool_calls_made
    mock.termination_reason = termination_reason
    mock.output = {"result": "done"}
    mock.raw_response = '{"result": "done"}'
    mock.model = "test-model"
    mock.tools_used = ["shell"]
    return mock


def _make_adapter(
    *,
    task: SkillsBenchTask | None = None,
    pytest_passed: bool = True,
    pytest_returncode: int = 0,
    agent_result: Any = None,
    agent_raises: Exception | None = None,
    task_raises: Exception | None = None,
    artifact_store: SkillsBenchArtifactStore | None = None,
) -> SkillsBenchAdapter:
    """Build a SkillsBenchAdapter with mocked dependencies."""
    # Task loader
    task_loader = MagicMock(spec=SkillsBenchTaskLoader)
    if task_raises is not None:
        task_loader.load_task.side_effect = task_raises
    else:
        task_loader.load_task.return_value = task or _make_task()
    task_loader.discover_tasks.return_value = [task or _make_task()]

    # Pytest runner
    pytest_runner = AsyncMock(spec=PytestBinaryRewardRunner)
    pytest_runner.evaluate.return_value = PytestResult(
        passed=pytest_passed,
        returncode=pytest_returncode,
        stdout="1 passed",
        stderr="",
        duration_ms=50.0,
    )

    # Skill registry
    skill_registry = MagicMock(spec=SkillRegistry)
    skill_registry.list_all.return_value = []
    skill_registry.discover.return_value = 0

    # Agent runtime
    agent_runtime = MagicMock()
    if agent_raises is not None:
        agent_runtime.invoke_iterative = AsyncMock(side_effect=agent_raises)
    else:
        agent_runtime.invoke_iterative = AsyncMock(
            return_value=agent_result or _make_iterative_result()
        )

    return SkillsBenchAdapter(
        task_loader=task_loader,
        pytest_runner=pytest_runner,
        skill_registry=skill_registry,
        agent_runtime=agent_runtime,
        artifact_store=artifact_store,
    )


# ---------------------------------------------------------------------------
# SkillsBenchAdapter.evaluate -- single trial
# ---------------------------------------------------------------------------


class TestSkillsBenchAdapterEvaluate:
    @pytest.mark.asyncio
    async def test_successful_trial_returns_success(self) -> None:
        adapter = _make_adapter(pytest_passed=True, pytest_returncode=0)
        outcome = await adapter.evaluate(
            task_id="math/addition",
            agent="code-worker",
            model="llama3.2",
            skills_enabled=False,
        )
        assert outcome.success is True
        assert outcome.tokens_used == 100
        assert outcome.metadata is not None
        assert outcome.metadata["task_id"] == "math/addition"

    @pytest.mark.asyncio
    async def test_failed_pytest_returns_failure(self) -> None:
        adapter = _make_adapter(pytest_passed=False, pytest_returncode=1)
        outcome = await adapter.evaluate(
            task_id="math/addition",
            agent="code-worker",
            model="llama3.2",
            skills_enabled=False,
        )
        assert outcome.success is False
        assert outcome.metadata is not None
        assert outcome.metadata["pytest_returncode"] == 1

    @pytest.mark.asyncio
    async def test_task_not_found_returns_failure(self) -> None:
        adapter = _make_adapter(task_raises=FileNotFoundError("Task directory not found"))
        outcome = await adapter.evaluate(
            task_id="nonexistent/task",
            agent="code-worker",
            model="llama3.2",
            skills_enabled=False,
        )
        assert outcome.success is False
        assert outcome.metadata is not None
        assert outcome.metadata["reason"] == "task_not_found"

    @pytest.mark.asyncio
    async def test_invalid_task_id_returns_failure(self) -> None:
        adapter = _make_adapter(
            task_raises=ValueError("task_id must be in 'category/task_name' format")
        )
        outcome = await adapter.evaluate(
            task_id="bad-id",
            agent="code-worker",
            model="llama3.2",
            skills_enabled=False,
        )
        assert outcome.success is False
        assert outcome.metadata is not None
        assert outcome.metadata["reason"] == "task_not_found"

    @pytest.mark.asyncio
    async def test_agent_error_returns_failure(self) -> None:
        adapter = _make_adapter(agent_raises=RuntimeError("LLM connection failed"))
        outcome = await adapter.evaluate(
            task_id="math/addition",
            agent="code-worker",
            model="llama3.2",
            skills_enabled=False,
        )
        assert outcome.success is False
        assert outcome.metadata is not None
        assert outcome.metadata["reason"] == "agent_error"
        assert "LLM connection failed" in outcome.metadata["error"]

    @pytest.mark.asyncio
    async def test_metadata_contains_agent_stats(self) -> None:
        result = _make_iterative_result(
            tokens_used=500,
            iterations=7,
            tool_calls_made=15,
            termination_reason="task_complete",
        )
        adapter = _make_adapter(agent_result=result, pytest_passed=True)
        outcome = await adapter.evaluate(
            task_id="math/addition",
            agent="code-worker",
            model="gpt-4o",
            skills_enabled=True,
        )
        assert outcome.success is True
        assert outcome.tokens_used == 500
        meta = outcome.metadata
        assert meta is not None
        assert meta["iterations"] == 7
        assert meta["tool_calls_made"] == 15
        assert meta["termination_reason"] == "task_complete"
        assert meta["agent"] == "code-worker"
        assert meta["model"] == "gpt-4o"
        assert meta["skills_enabled"] is True

    @pytest.mark.asyncio
    async def test_skills_enabled_triggers_loading(self) -> None:
        task = _make_task(skills_dir=Path("/fake/skills"))
        adapter = _make_adapter(task=task, pytest_passed=True)
        outcome = await adapter.evaluate(
            task_id="math/addition",
            agent="code-worker",
            model="llama3.2",
            skills_enabled=True,
        )
        assert outcome.success is True
        # Verify skill registry discover was called
        adapter._skill_registry.discover.assert_called_once_with(Path("/fake/skills"))
        adapter._skill_registry.remove.assert_not_called()

    @pytest.mark.asyncio
    async def test_skills_disabled_skips_loading(self) -> None:
        task = _make_task(skills_dir=Path("/fake/skills"))
        adapter = _make_adapter(task=task, pytest_passed=True)
        await adapter.evaluate(
            task_id="math/addition",
            agent="code-worker",
            model="llama3.2",
            skills_enabled=False,
        )
        adapter._skill_registry.discover.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_skills_dir_skips_loading(self) -> None:
        task = _make_task(skills_dir=None)
        adapter = _make_adapter(task=task, pytest_passed=True)
        await adapter.evaluate(
            task_id="math/addition",
            agent="code-worker",
            model="llama3.2",
            skills_enabled=True,
        )
        adapter._skill_registry.discover.assert_not_called()

    @pytest.mark.asyncio
    async def test_loaded_skills_are_removed_after_trial(self) -> None:
        task = _make_task(skills_dir=Path("/fake/skills"))
        adapter = _make_adapter(task=task, pytest_passed=True)
        skill_a = MagicMock()
        skill_a.name = "skill-a"
        adapter._skill_registry.list_all.side_effect = [[], [skill_a]]
        adapter._skill_registry.discover.return_value = 1

        outcome = await adapter.evaluate(
            task_id="math/addition",
            agent="code-worker",
            model="llama3.2",
            skills_enabled=True,
        )

        assert outcome.success is True
        adapter._skill_registry.remove.assert_called_once_with("skill-a")


# ---------------------------------------------------------------------------
# SkillsBenchAdapter._load_bundled_skills
# ---------------------------------------------------------------------------


class TestSkillsBenchAdapterLoadSkills:
    def test_load_skills_returns_new_names(self) -> None:
        adapter = _make_adapter()
        # Simulate adding skills: before=[]; after=["skill-a", "skill-b"]
        skill_a = MagicMock()
        skill_a.name = "skill-a"
        skill_b = MagicMock()
        skill_b.name = "skill-b"

        adapter._skill_registry.list_all.side_effect = [
            [],  # before
            [skill_a, skill_b],  # after
        ]
        adapter._skill_registry.discover.return_value = 2

        names = adapter._load_bundled_skills(Path("/fake/skills"), "math/add")
        assert set(names) == {"skill-a", "skill-b"}

    def test_load_skills_handles_error(self) -> None:
        adapter = _make_adapter()
        adapter._skill_registry.list_all.return_value = []
        adapter._skill_registry.discover.side_effect = RuntimeError("Bad skills dir")

        names = adapter._load_bundled_skills(Path("/fake/skills"), "math/add")
        assert names == []


# ---------------------------------------------------------------------------
# SkillsBenchAdapter.run_benchmark
# ---------------------------------------------------------------------------


class TestSkillsBenchAdapterRunBenchmark:
    @pytest.mark.asyncio
    async def test_run_benchmark_completes(self) -> None:
        adapter = _make_adapter(pytest_passed=True)
        config = SkillsBenchConfig(
            skillsbench_root=Path("/fake"),
            agent_name="code-worker",
            model="llama3.2",
            trials_per_task=2,
            skills_enabled=False,
        )
        result = await adapter.run_benchmark(config)
        assert result.status == BenchmarkRunStatus.COMPLETED
        assert result.total_trials == 2
        assert result.passed_trials == 2
        assert result.pass_rate == 1.0
        assert result.run_id.startswith("sb-")

    @pytest.mark.asyncio
    async def test_run_benchmark_mixed_results(self) -> None:
        """Alternate pass/fail across trials."""
        adapter = _make_adapter()
        # First call passes, second fails
        adapter._pytest_runner.evaluate = AsyncMock(
            side_effect=[
                PytestResult(passed=True, returncode=0, stdout="", stderr="", duration_ms=10),
                PytestResult(passed=False, returncode=1, stdout="", stderr="", duration_ms=10),
            ]
        )
        config = SkillsBenchConfig(
            skillsbench_root=Path("/fake"),
            trials_per_task=2,
            skills_enabled=False,
        )
        result = await adapter.run_benchmark(config)
        assert result.status == BenchmarkRunStatus.COMPLETED
        assert result.total_trials == 2
        assert result.passed_trials == 1
        assert result.failed_trials == 1
        assert result.pass_rate == 0.5

    @pytest.mark.asyncio
    async def test_run_benchmark_no_tasks(self) -> None:
        adapter = _make_adapter()
        adapter._task_loader.discover_tasks.return_value = []
        config = SkillsBenchConfig(
            skillsbench_root=Path("/fake"),
            trials_per_task=1,
        )
        result = await adapter.run_benchmark(config)
        assert result.status == BenchmarkRunStatus.COMPLETED
        assert result.total_trials == 0
        assert result.total_tasks == 0

    @pytest.mark.asyncio
    async def test_run_benchmark_discovery_error(self) -> None:
        adapter = _make_adapter()
        adapter._task_loader.discover_tasks.side_effect = OSError("Disk error")
        config = SkillsBenchConfig(
            skillsbench_root=Path("/fake"),
            trials_per_task=1,
        )
        result = await adapter.run_benchmark(config)
        assert result.status == BenchmarkRunStatus.FAILED

    @pytest.mark.asyncio
    async def test_run_benchmark_trial_records_contain_metadata(self) -> None:
        adapter = _make_adapter(pytest_passed=True)
        config = SkillsBenchConfig(
            skillsbench_root=Path("/fake"),
            agent_name="test-agent",
            model="test-model",
            trials_per_task=1,
            skills_enabled=True,
        )
        result = await adapter.run_benchmark(config)
        assert len(result.trials) == 1
        trial = result.trials[0]
        assert trial.agent == "test-agent"
        assert trial.model == "test-model"
        assert trial.skills_enabled is True
        assert trial.outcome == TrialOutcome.PASSED
        assert trial.trial_number == 1

    @pytest.mark.asyncio
    async def test_run_benchmark_persists_trial_artifacts(self, tmp_path: Path) -> None:
        store = SkillsBenchArtifactStore(tmp_path / "skillsbench-store")
        adapter = _make_adapter(pytest_passed=True, artifact_store=store)
        config = SkillsBenchConfig(
            skillsbench_root=Path("/fake"),
            trials_per_task=1,
            skills_enabled=False,
        )

        result = await adapter.run_benchmark(config)

        assert len(result.trials) == 1
        trial = result.trials[0]
        assert {artifact.kind for artifact in trial.artifacts} == {
            "pytest_stdout",
            "agent_output",
            "agent_raw_response",
        }
        assert (store.base_path / result.run_id / "run.json").is_file()
        assert trial.pytest_stdout_excerpt == "1 passed"

    @pytest.mark.asyncio
    async def test_run_benchmark_agent_error_produces_error_outcome(self) -> None:
        adapter = _make_adapter(agent_raises=RuntimeError("LLM timeout"))
        config = SkillsBenchConfig(
            skillsbench_root=Path("/fake"),
            trials_per_task=1,
            skills_enabled=False,
        )
        result = await adapter.run_benchmark(config)
        assert result.status == BenchmarkRunStatus.COMPLETED
        assert len(result.trials) == 1
        assert result.trials[0].outcome == TrialOutcome.ERROR
        assert "LLM timeout" in result.trials[0].error_message
