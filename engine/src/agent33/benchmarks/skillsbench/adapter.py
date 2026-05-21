"""Bridge TrialEvaluatorAdapter to real agent invocations with SkillsBench tasks.

The adapter wires together:

1. :class:`SkillsBenchTaskLoader` -- locates and loads task instructions and
   bundled skills.
2. :class:`~agent33.skills.registry.SkillRegistry` -- registers bundled skills
   scoped to the current trial when ``skills_enabled=True``.
3. :class:`~agent33.agents.runtime.AgentRuntime` -- the agent that actually
   runs the task instruction via the iterative tool-use loop.
4. :class:`PytestBinaryRewardRunner` -- verifies agent outputs using the task's
   pytest file and returns binary pass/fail.

The adapter implements the :class:`~agent33.evaluation.service.TrialEvaluatorAdapter`
protocol so it can be plugged directly into :class:`~agent33.evaluation.service.EvaluationService`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent33.benchmarks.skillsbench.models import (
    BenchmarkRunResult,
    BenchmarkRunStatus,
    TrialArtifact,
    TrialOutcome,
    TrialRecord,
)
from agent33.evaluation.service import TrialEvaluationOutcome

if TYPE_CHECKING:
    from agent33.agents.runtime import AgentRuntime
    from agent33.benchmarks.skillsbench.config import SkillsBenchConfig
    from agent33.benchmarks.skillsbench.runner import PytestBinaryRewardRunner
    from agent33.benchmarks.skillsbench.storage import SkillsBenchArtifactStore
    from agent33.benchmarks.skillsbench.task_loader import (
        SkillsBenchTask,
        SkillsBenchTaskLoader,
    )
    from agent33.skills.matching import SkillMatcher
    from agent33.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


class SkillsBenchAdapter:
    """Implements TrialEvaluatorAdapter for real SkillsBench evaluation.

    Pipeline per trial:

    1. Load task instruction and skills.
    2. If ``skills_enabled``: load bundled skills from the task's ``environment/skills/``
       directory and inject them into the agent.
    3. Invoke :meth:`AgentRuntime.invoke_iterative` with the task instruction,
       writing any file outputs to a temporary working directory.
    4. Run pytest binary reward on the outputs in that directory.
    5. Return a :class:`~agent33.evaluation.service.TrialEvaluationOutcome`.

    Parameters
    ----------
    task_loader:
        Discovers and loads SkillsBench tasks from disk.
    pytest_runner:
        Runs pytest to determine binary pass/fail.
    skill_registry:
        The base :class:`~agent33.skills.registry.SkillRegistry`; bundled
        task skills are registered into it temporarily.
    agent_runtime:
        The :class:`~agent33.agents.runtime.AgentRuntime` instance to invoke.
    skill_matcher:
        Optional 4-stage skill matcher; if provided, it is used to select
        relevant skills from the task's bundled skills directory.
    """

    def __init__(
        self,
        task_loader: SkillsBenchTaskLoader,
        pytest_runner: PytestBinaryRewardRunner,
        skill_registry: SkillRegistry,
        agent_runtime: AgentRuntime,
        skill_matcher: SkillMatcher | None = None,
        artifact_store: SkillsBenchArtifactStore | None = None,
    ) -> None:
        self._task_loader = task_loader
        self._pytest_runner = pytest_runner
        self._skill_registry = skill_registry
        self._agent_runtime = agent_runtime
        self._skill_matcher = skill_matcher
        self._artifact_store = artifact_store
        self._active_skills_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # TrialEvaluatorAdapter protocol
    # ------------------------------------------------------------------

    async def evaluate(
        self,
        *,
        task_id: str,
        agent: str,
        model: str,
        skills_enabled: bool,
        **kwargs: Any,
    ) -> TrialEvaluationOutcome:
        """Execute one trial of a SkillsBench task.

        Parameters
        ----------
        task_id:
            SkillsBench task identifier in ``category/task_name`` format.
        agent:
            Agent name (used for logging; ``agent_runtime`` is already bound).
        model:
            LLM model string (used for logging; model selection is handled by
            the runtime's router).
        skills_enabled:
            If ``True``, load bundled skills from the task's ``environment/skills/``
            directory and inject them into the agent.
        **kwargs:
            Ignored; preserved for forward-compatibility.

        Returns
        -------
        TrialEvaluationOutcome
            ``success=True`` iff all pytest tests passed.
        """
        logger.info(
            "skillsbench_trial_start task=%s agent=%s model=%s skills=%s",
            task_id,
            agent,
            model,
            skills_enabled,
        )

        # 1. Load task
        try:
            task = self._task_loader.load_task(task_id)
        except (FileNotFoundError, ValueError) as exc:
            logger.warning("skillsbench_task_not_found task=%s error=%s", task_id, exc)
            return TrialEvaluationOutcome(
                success=False,
                metadata={"reason": "task_not_found", "error": str(exc)},
            )

        # 2. Load bundled skills when enabled
        loaded_skill_names: list[str] = []
        if skills_enabled and task.skills_dir is not None:
            loaded_skill_names = self._load_bundled_skills(task.skills_dir, task_id)

        # 2b. If a 4-stage skill matcher is configured, filter to relevant skills only.
        # This prevents answer-leaking skills from being injected while preserving
        # access to genuinely relevant bundled skills.
        staged_matching_skipped = False
        if self._skill_matcher is not None and loaded_skill_names:
            self._skill_matcher.reindex()
            try:
                match_result = await self._skill_matcher.match(task.instruction)
                matched_names: set[str] = {s.name for s in match_result.skills}
                rejected = [n for n in loaded_skill_names if n not in matched_names]
                self._unload_bundled_skills(rejected)
                loaded_skill_names = [n for n in loaded_skill_names if n in matched_names]
                logger.info(
                    "skillsbench_staged_matching task=%s total=%d matched=%d rejected=%d",
                    task_id,
                    len(loaded_skill_names) + len(rejected),
                    len(loaded_skill_names),
                    len(rejected),
                )
            except Exception as exc:
                logger.warning(
                    "skillsbench_staged_matching_error task=%s error=%s",
                    task_id,
                    exc,
                    exc_info=True,
                )
                # Fall back to using all loaded skills on matcher failure
                staged_matching_skipped = True  # Architecture & Planning A-04

        # 3. Invoke agent in a fresh temporary working directory
        with tempfile.TemporaryDirectory(prefix="skillsbench_") as tmp_str:
            working_dir = Path(tmp_str)

            inputs: dict[str, Any] = {
                "instruction": task.instruction,
                "task_id": task_id,
                "working_dir": str(working_dir),
                "skills_enabled": skills_enabled,
            }

            tokens_used = 0
            trial_metadata: dict[str, Any] = {
                "task_id": task_id,
                "agent": agent,
                "model": model,
                "skills_enabled": skills_enabled,
                "loaded_skills": loaded_skill_names,
                "staged_matching_skipped": staged_matching_skipped,
            }

            # Guard _active_skills mutation with a lock so concurrent
            # trials sharing the same AgentRuntime cannot race on the
            # snapshot-mutate-restore cycle.  (Architecture & Planning A-01)
            async with self._active_skills_lock:
                original_active_skills: list[str] | None = None
                if loaded_skill_names:
                    runtime_any = self._agent_runtime
                    active_skills = getattr(runtime_any, "_active_skills", None)
                    if isinstance(active_skills, list):
                        original_active_skills = list(active_skills)
                        runtime_any._active_skills = list(
                            dict.fromkeys([*active_skills, *loaded_skill_names])
                        )

                try:
                    result = await self._agent_runtime.invoke_iterative(inputs=inputs)
                    tokens_used = result.tokens_used
                    trial_metadata["iterations"] = result.iterations
                    trial_metadata["tool_calls_made"] = result.tool_calls_made
                    trial_metadata["termination_reason"] = result.termination_reason
                    trial_metadata["agent_output"] = self._serialize_agent_payload(
                        getattr(result, "output", {})
                    )
                    trial_metadata["agent_raw_response"] = str(getattr(result, "raw_response", ""))
                except Exception as exc:
                    logger.warning(
                        "skillsbench_agent_error task=%s error=%s",
                        task_id,
                        exc,
                        exc_info=True,
                    )
                    return TrialEvaluationOutcome(
                        success=False,
                        tokens_used=tokens_used,
                        metadata={
                            **trial_metadata,
                            "error": str(exc),
                            "reason": "agent_error",
                        },
                    )
                finally:
                    if original_active_skills is not None:
                        runtime_any._active_skills = original_active_skills
                    self._unload_bundled_skills(loaded_skill_names)

            # 4. Run pytest binary reward
            pytest_result = await self._pytest_runner.evaluate(
                tests_path=task.tests_path,
                working_dir=working_dir,
            )

        trial_metadata["pytest_returncode"] = pytest_result.returncode
        trial_metadata["pytest_duration_ms"] = pytest_result.duration_ms
        trial_metadata["pytest_stdout"] = pytest_result.stdout
        trial_metadata["pytest_stderr"] = pytest_result.stderr

        logger.info(
            "skillsbench_trial_complete task=%s passed=%s returncode=%d",
            task_id,
            pytest_result.passed,
            pytest_result.returncode,
        )

        return TrialEvaluationOutcome(
            success=pytest_result.passed,
            tokens_used=tokens_used,
            metadata=trial_metadata,
        )

    # ------------------------------------------------------------------
    # Batch run
    # ------------------------------------------------------------------

    async def run_benchmark(
        self,
        config: SkillsBenchConfig,
    ) -> BenchmarkRunResult:
        """Run a full benchmark according to the given configuration.

        Discovers tasks, runs the specified number of trials per task,
        and aggregates results.

        Parameters
        ----------
        config:
            SkillsBench configuration with task directory, filter, and
            trial count.

        Returns
        -------
        BenchmarkRunResult
            Aggregated benchmark results with per-trial records.
        """
        run_id = f"sb-{uuid.uuid4().hex[:12]}"
        run_result = BenchmarkRunResult(
            run_id=run_id,
            status=BenchmarkRunStatus.RUNNING,
            config_summary={
                "skillsbench_root": str(config.skillsbench_root),
                "agent_name": config.agent_name,
                "model": config.model,
                "trials_per_task": config.trials_per_task,
                "skills_enabled": config.skills_enabled,
            },
        )

        logger.info(
            "skillsbench_benchmark_start run_id=%s agent=%s model=%s trials=%d",
            run_id,
            config.agent_name,
            config.model,
            config.trials_per_task,
        )

        try:
            tasks = self._task_loader.discover_tasks(task_filter=config.task_filter)
        except Exception as exc:
            logger.error("skillsbench_discovery_error run_id=%s error=%s", run_id, exc)
            run_result.status = BenchmarkRunStatus.FAILED
            return run_result

        if not tasks:
            logger.warning("skillsbench_no_tasks run_id=%s", run_id)
            run_result.status = BenchmarkRunStatus.COMPLETED
            run_result.completed_at = datetime.now(UTC)
            return run_result

        for task in tasks:
            for trial_num in range(1, config.trials_per_task + 1):
                record = await self._run_single_trial(
                    run_id=run_id,
                    task=task,
                    trial_number=trial_num,
                    agent=config.agent_name,
                    model=config.model,
                    skills_enabled=config.skills_enabled,
                )
                run_result.trials.append(record)

        run_result.compute_aggregates()
        run_result.status = BenchmarkRunStatus.COMPLETED
        run_result.completed_at = datetime.now(UTC)
        run_result.artifact_root = run_id
        if self._artifact_store is not None:
            self._artifact_store.persist_run(run_result)

        logger.info(
            "skillsbench_benchmark_complete run_id=%s tasks=%d trials=%d pass_rate=%.2f",
            run_id,
            run_result.total_tasks,
            run_result.total_trials,
            run_result.pass_rate,
        )

        return run_result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _run_single_trial(
        self,
        run_id: str,
        task: SkillsBenchTask,
        trial_number: int,
        agent: str,
        model: str,
        skills_enabled: bool,
    ) -> TrialRecord:
        """Execute a single trial and return a TrialRecord."""
        start = time.monotonic()

        outcome = await self.evaluate(
            task_id=task.task_id,
            agent=agent,
            model=model,
            skills_enabled=skills_enabled,
        )

        duration_ms = (time.monotonic() - start) * 1000.0

        if outcome.success:
            trial_outcome = TrialOutcome.PASSED
        elif outcome.metadata and outcome.metadata.get("reason") == "agent_error":
            trial_outcome = TrialOutcome.ERROR
        else:
            trial_outcome = TrialOutcome.FAILED

        meta = outcome.metadata or {}
        stdout_excerpt = str(meta.get("pytest_stdout", ""))[:400]
        stderr_excerpt = str(meta.get("pytest_stderr", ""))[:400]
        artifacts = self._persist_trial_artifacts(
            run_id=run_id,
            task_id=task.task_id,
            trial_number=trial_number,
            metadata=meta,
        )

        return TrialRecord(
            task_id=task.task_id,
            trial_number=trial_number,
            outcome=trial_outcome,
            duration_ms=duration_ms,
            tokens_used=outcome.tokens_used,
            agent=agent,
            model=model,
            skills_enabled=skills_enabled,
            iterations=meta.get("iterations", 0),
            tool_calls_made=meta.get("tool_calls_made", 0),
            termination_reason=meta.get("termination_reason", ""),
            pytest_returncode=meta.get("pytest_returncode", -1),
            error_message=meta.get("error", ""),
            pytest_stdout_excerpt=stdout_excerpt,
            pytest_stderr_excerpt=stderr_excerpt,
            artifacts=artifacts,
            metadata=meta,
        )

    def _load_bundled_skills(self, skills_dir: Path, task_id: str) -> list[str]:
        """Load skills from a task's bundled skills directory.

        Returns the names of the skills that were successfully loaded.
        """
        before_names = {s.name for s in self._skill_registry.list_all()}
        try:
            count = self._skill_registry.discover(skills_dir)
            after_names = {s.name for s in self._skill_registry.list_all()}
            new_names = sorted(after_names - before_names)
            logger.info(
                "skillsbench_skills_loaded task=%s count=%d names=%s",
                task_id,
                count,
                new_names,
            )
            return new_names
        except Exception as exc:
            logger.warning(
                "skillsbench_skills_load_error task=%s error=%s", task_id, exc, exc_info=True
            )
            return []

    def _unload_bundled_skills(self, loaded_skill_names: list[str]) -> None:
        """Remove task-scoped skills after a trial to avoid cross-trial leakage."""
        for skill_name in loaded_skill_names:
            self._skill_registry.remove(skill_name)

    def _persist_trial_artifacts(
        self,
        *,
        run_id: str,
        task_id: str,
        trial_number: int,
        metadata: dict[str, Any],
    ) -> list[TrialArtifact]:
        """Persist per-trial artifacts and return their metadata records."""
        if self._artifact_store is None:
            return []

        artifact_specs = [
            ("pytest_stdout", "pytest-stdout.txt", str(metadata.pop("pytest_stdout", ""))),
            ("pytest_stderr", "pytest-stderr.txt", str(metadata.pop("pytest_stderr", ""))),
            ("agent_output", "agent-output.txt", str(metadata.pop("agent_output", ""))),
            (
                "agent_raw_response",
                "agent-raw-response.txt",
                str(metadata.pop("agent_raw_response", "")),
            ),
        ]

        artifacts: list[TrialArtifact] = []
        for kind, filename, content in artifact_specs:
            if not content:
                continue
            artifacts.append(
                self._artifact_store.persist_text_artifact(
                    run_id=run_id,
                    task_id=task_id,
                    trial_number=trial_number,
                    kind=kind,
                    filename=filename,
                    content=content,
                )
            )
        return artifacts

    def _serialize_agent_payload(self, payload: Any) -> str:
        """Normalize agent output payloads for artifact persistence."""
        if isinstance(payload, str):
            return payload
        try:
            return json.dumps(payload, indent=2, sort_keys=True)
        except TypeError:
            return str(payload)
