"""Tests for 4-stage SkillMatcher wiring into SkillRegistry and SkillsBenchAdapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from agent33.benchmarks.skillsbench.adapter import SkillsBenchAdapter
from agent33.skills.definition import SkillDefinition
from agent33.skills.matching import SkillMatchResult
from agent33.skills.registry import SkillRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_skill(name: str, description: str = "") -> SkillDefinition:
    """Create a minimal SkillDefinition for testing."""
    return SkillDefinition(name=name, description=description or f"Skill {name}")


def _make_task(
    task_id: str = "cat/task1",
    instruction: str = "Do something",
    skills_dir: Path | None = Path("/fake/skills"),
) -> Any:
    """Create a mock SkillsBenchTask."""
    task = MagicMock()
    task.task_id = task_id
    task.category = "cat"
    task.instruction = instruction
    task.skills_dir = skills_dir
    task.tests_path = Path("/fake/tests/test_outputs.py")
    return task


# ===========================================================================
# TestSkillRegistrySearchStaged
# ===========================================================================


class TestSkillRegistrySearchStaged:
    """Tests for SkillRegistry.search_staged() delegation to SkillMatcher."""

    async def test_search_staged_delegates_to_matcher(self) -> None:
        """search_staged() should return the skills from matcher.match()."""
        registry = SkillRegistry()
        skill_a = _make_skill("skill-a", "Alpha skill")
        skill_b = _make_skill("skill-b", "Beta skill")

        match_result = SkillMatchResult(
            skills=[skill_a, skill_b],
            stage1_count=5,
            stage2_count=3,
            stage4_count=2,
        )

        matcher = MagicMock()
        matcher.match = AsyncMock(return_value=match_result)

        result = await registry.search_staged("find alpha and beta", matcher)

        matcher.match.assert_awaited_once_with("find alpha and beta")
        assert result == [skill_a, skill_b]
        assert len(result) == 2
        assert result[0].name == "skill-a"
        assert result[1].name == "skill-b"

    async def test_search_staged_empty_result(self) -> None:
        """search_staged() should return [] when matcher finds no skills."""
        registry = SkillRegistry()

        match_result = SkillMatchResult(skills=[], stage1_count=0)

        matcher = MagicMock()
        matcher.match = AsyncMock(return_value=match_result)

        result = await registry.search_staged("nonexistent query", matcher)

        matcher.match.assert_awaited_once_with("nonexistent query")
        assert result == []


# ===========================================================================
# TestSkillsBenchAdapterStagedMatching
# ===========================================================================


class TestSkillsBenchAdapterStagedMatching:
    """Tests for staged matching wiring in SkillsBenchAdapter.evaluate()."""

    def _make_adapter(
        self,
        *,
        skill_matcher: Any = None,
        loaded_skills: list[str] | None = None,
    ) -> tuple[SkillsBenchAdapter, MagicMock, MagicMock, MagicMock, MagicMock]:
        """Build a SkillsBenchAdapter with fully mocked dependencies.

        Returns (adapter, task_loader, pytest_runner, skill_registry, agent_runtime).
        """
        task_loader = MagicMock()
        pytest_runner = MagicMock()
        pytest_runner.evaluate = AsyncMock(
            return_value=MagicMock(
                passed=True, returncode=0, duration_ms=100.0, stdout="", stderr=""
            )
        )
        skill_registry = MagicMock(spec=SkillRegistry)
        skill_registry.list_all.return_value = []
        agent_runtime = MagicMock()
        agent_runtime.invoke_iterative = AsyncMock(
            return_value=MagicMock(
                tokens_used=100,
                iterations=2,
                tool_calls_made=1,
                termination_reason="complete",
                output={"result": "done"},
                raw_response="done",
            )
        )
        # No _active_skills attribute by default
        agent_runtime._active_skills = None

        adapter = SkillsBenchAdapter(
            task_loader=task_loader,
            pytest_runner=pytest_runner,
            skill_registry=skill_registry,
            agent_runtime=agent_runtime,
            skill_matcher=skill_matcher,
        )

        return adapter, task_loader, pytest_runner, skill_registry, agent_runtime

    async def test_evaluate_with_matcher_filters_skills(self) -> None:
        """When skill_matcher is set, only matched skills survive; rejected are unloaded."""
        # Set up matcher that matches only skill_a
        skill_a = _make_skill("skill_a")
        match_result = SkillMatchResult(
            skills=[skill_a],
            stage1_count=3,
            stage2_count=2,
            stage4_count=1,
        )
        skill_matcher = MagicMock()
        skill_matcher.reindex = MagicMock()
        skill_matcher.match = AsyncMock(return_value=match_result)

        adapter, task_loader, pytest_runner, skill_registry, agent_runtime = self._make_adapter(
            skill_matcher=skill_matcher,
        )

        # Set up task
        task = _make_task(instruction="Calculate the area of a circle")
        task_loader.load_task.return_value = task

        # Mock _load_bundled_skills to return 3 skills
        with (
            patch.object(
                adapter, "_load_bundled_skills", return_value=["skill_a", "skill_b", "skill_c"]
            ),
            patch.object(adapter, "_unload_bundled_skills") as mock_unload,
        ):
            outcome = await adapter.evaluate(
                task_id="cat/task1",
                agent="code-worker",
                model="llama3.2",
                skills_enabled=True,
            )

        # Verify matcher was called
        skill_matcher.reindex.assert_called_once()
        skill_matcher.match.assert_awaited_once_with("Calculate the area of a circle")

        # Verify rejected skills were unloaded (skill_b and skill_c)
        # The first call to _unload_bundled_skills should be with rejected skills
        unload_calls = mock_unload.call_args_list
        # First call: staged matching rejects skill_b and skill_c
        assert unload_calls[0].args[0] == ["skill_b", "skill_c"]
        # Second call: cleanup in finally block with surviving skills
        assert unload_calls[1].args[0] == ["skill_a"]

        # Verify outcome succeeded
        assert outcome.success is True
        # loaded_skills in metadata should reflect the filtered list
        assert outcome.metadata is not None
        assert outcome.metadata["loaded_skills"] == ["skill_a"]

    async def test_evaluate_without_matcher_loads_all(self) -> None:
        """When no skill_matcher is set, all loaded skills are used unchanged."""
        adapter, task_loader, pytest_runner, skill_registry, agent_runtime = self._make_adapter(
            skill_matcher=None,
        )

        task = _make_task(instruction="Do something")
        task_loader.load_task.return_value = task

        with (
            patch.object(
                adapter, "_load_bundled_skills", return_value=["skill_a", "skill_b", "skill_c"]
            ),
            patch.object(adapter, "_unload_bundled_skills") as mock_unload,
        ):
            outcome = await adapter.evaluate(
                task_id="cat/task1",
                agent="code-worker",
                model="llama3.2",
                skills_enabled=True,
            )

        # No staged matching unload should have happened
        # Only the finally-block cleanup unload should happen
        assert mock_unload.call_count == 1
        # The only unload is the finally-block with all 3 skills
        assert mock_unload.call_args.args[0] == ["skill_a", "skill_b", "skill_c"]

        assert outcome.success is True
        assert outcome.metadata is not None
        assert outcome.metadata["loaded_skills"] == ["skill_a", "skill_b", "skill_c"]

    async def test_evaluate_matcher_error_falls_back(self) -> None:
        """When matcher.match() raises, all originally loaded skills remain active."""
        skill_matcher = MagicMock()
        skill_matcher.reindex = MagicMock()
        skill_matcher.match = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

        adapter, task_loader, pytest_runner, skill_registry, agent_runtime = self._make_adapter(
            skill_matcher=skill_matcher,
        )

        task = _make_task(instruction="Solve a puzzle")
        task_loader.load_task.return_value = task

        with (
            patch.object(adapter, "_load_bundled_skills", return_value=["skill_a", "skill_b"]),
            patch.object(adapter, "_unload_bundled_skills") as mock_unload,
        ):
            outcome = await adapter.evaluate(
                task_id="cat/task1",
                agent="code-worker",
                model="llama3.2",
                skills_enabled=True,
            )

        # Matcher was attempted
        skill_matcher.reindex.assert_called_once()
        skill_matcher.match.assert_awaited_once_with("Solve a puzzle")

        # No skills should have been unloaded by the staged matching (error path)
        # Only the finally-block cleanup should have unloaded all skills
        assert mock_unload.call_count == 1
        assert mock_unload.call_args.args[0] == ["skill_a", "skill_b"]

        # Trial should still succeed (agent runs with all skills)
        assert outcome.success is True
        assert outcome.metadata is not None
        assert outcome.metadata["loaded_skills"] == ["skill_a", "skill_b"]

    async def test_evaluate_no_skills_skips_matcher(self) -> None:
        """When skills_enabled=False, matcher.match() is never called."""
        skill_matcher = MagicMock()
        skill_matcher.reindex = MagicMock()
        skill_matcher.match = AsyncMock()

        adapter, task_loader, pytest_runner, skill_registry, agent_runtime = self._make_adapter(
            skill_matcher=skill_matcher,
        )

        task = _make_task(instruction="Simple task", skills_dir=None)
        task_loader.load_task.return_value = task

        outcome = await adapter.evaluate(
            task_id="cat/task1",
            agent="code-worker",
            model="llama3.2",
            skills_enabled=False,
        )

        # Matcher should never be called when skills are disabled
        skill_matcher.reindex.assert_not_called()
        skill_matcher.match.assert_not_awaited()

        assert outcome.success is True
