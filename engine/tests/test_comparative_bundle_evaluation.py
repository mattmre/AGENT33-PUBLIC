"""Tests for bundle-scoped A5/A6 comparative evaluation."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent33.evaluation.comparative.models import AgentScore
from agent33.evaluation.comparative.service import ComparativeEvaluationService
from agent33.evaluation.synthetic_envs.service import SyntheticEnvironmentService


def _bundle(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    service = SyntheticEnvironmentService(
        workflow_dir=root / "workflow-definitions",
        tool_dir=root / "tool-definitions",
        persistence_path=tmp_path / "bundles.json",
    )
    return service.generate_bundle(
        workflow_names=["incident-triage-loop"],
        variations_per_workflow=1,
    )


def test_record_bundle_scores_namespaces_task_ids(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    comparative = ComparativeEvaluationService()
    task = bundle.environments[0].tasks[0]

    recorded = comparative.record_bundle_scores(
        bundle.bundle_id,
        [
            AgentScore(
                agent_name="alpha",
                metric_name="M-01",
                value=0.9,
                task_id=task.task_id,
            )
        ],
        allowed_task_ids={task.task_id},
    )

    assert recorded[0].task_id == f"{bundle.bundle_id}::{task.task_id}"


def test_record_bundle_scores_rejects_unknown_task_ids(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    comparative = ComparativeEvaluationService()

    with pytest.raises(ValueError, match="Unknown bundle task IDs"):
        comparative.record_bundle_scores(
            bundle.bundle_id,
            [
                AgentScore(
                    agent_name="alpha",
                    metric_name="M-01",
                    value=0.9,
                    task_id="TASK-missing",
                )
            ],
            allowed_task_ids={task.task_id for env in bundle.environments for task in env.tasks},
        )


def test_record_bundle_scores_rejects_missing_task_ids(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    comparative = ComparativeEvaluationService()

    with pytest.raises(ValueError, match="Unknown bundle task IDs: <missing>"):
        comparative.record_bundle_scores(
            bundle.bundle_id,
            [
                AgentScore(
                    agent_name="alpha",
                    metric_name="M-01",
                    value=0.9,
                    task_id=None,
                )
            ],
            allowed_task_ids={task.task_id for env in bundle.environments for task in env.tasks},
        )


def test_bundle_evaluation_uses_only_shared_task_ids(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    comparative = ComparativeEvaluationService()
    tasks = [task.task_id for env in bundle.environments for task in env.tasks]
    first, second = tasks[:2]

    comparative.record_bundle_scores(
        bundle.bundle_id,
        [
            AgentScore(agent_name="alpha", metric_name="M-01", value=0.9, task_id=first),
            AgentScore(agent_name="alpha", metric_name="M-01", value=0.8, task_id=second),
            AgentScore(agent_name="beta", metric_name="M-01", value=0.7, task_id=first),
            AgentScore(agent_name="beta", metric_name="M-01", value=0.6, task_id=second),
            AgentScore(agent_name="gamma", metric_name="M-01", value=0.5, task_id=first),
        ],
        allowed_task_ids=set(tasks),
    )

    comparisons, leaderboard = comparative.run_bundle_round_robin(bundle.bundle_id, "M-01")

    assert leaderboard.task_ids == [first]
    assert leaderboard.entries[0].agent_name == "alpha"
    assert len(comparisons) == 3
