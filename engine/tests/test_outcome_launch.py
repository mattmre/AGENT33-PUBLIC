from __future__ import annotations

from agent33.outcomes.launch import (
    LaunchScale,
    OutcomeLaunchIntake,
    build_guided_launch_plan,
    evaluate_outcome_launch_friction,
    recommend_outcome_launch,
)


def test_recommend_outcome_launch_routes_research_objective() -> None:
    recommendation = recommend_outcome_launch(
        OutcomeLaunchIntake(objective="Research competitors for the new product")
    )

    assert recommendation.scale == LaunchScale.RESEARCH_WORKFLOW
    assert recommendation.recommended_workflow == "github.issue-triage"
    assert recommendation.recommended_pack == "research-brief"
    assert recommendation.recommended_runtime == "agent-os"
    assert "prepare dry-run workflow plan" in recommendation.preview_steps


def test_recommend_outcome_launch_uses_project_context() -> None:
    recommendation = recommend_outcome_launch(
        OutcomeLaunchIntake(
            objective="Ship onboarding",
            project_name="operator cockpit",
            preferred_model="openrouter/auto",
        )
    )

    assert recommendation.scale == LaunchScale.PROJECT_BUILD
    assert recommendation.recommended_workflow == "github.pr-review"
    assert recommendation.recommended_model == "openrouter/auto"


def test_evaluate_outcome_launch_friction_flags_missing_launch_inputs() -> None:
    evaluation = evaluate_outcome_launch_friction(OutcomeLaunchIntake(objective="Build it"))

    assert evaluation.recommendation.scale == LaunchScale.PROJECT_BUILD
    assert evaluation.readiness == "blocked"
    assert evaluation.friction_score == 65
    assert [signal.id for signal in evaluation.signals] == [
        "objective-too-thin",
        "missing-project-context",
        "missing-constraints",
        "model-not-selected",
    ]
    assert evaluation.signals[0].step == "confirm objective and constraints"


def test_evaluate_outcome_launch_friction_can_be_ready_for_complete_intake() -> None:
    evaluation = evaluate_outcome_launch_friction(
        OutcomeLaunchIntake(
            objective="Research competitor pricing and summarize risks",
            project_name="market scan",
            preferred_model="openrouter/auto",
            constraints=["finish under one hour", "no browser mutation"],
        )
    )

    assert evaluation.readiness == "ready"
    assert evaluation.friction_score == 0
    assert evaluation.signals == []


def test_build_guided_launch_plan_collects_missing_answers_before_runnable_preview() -> None:
    plan = build_guided_launch_plan(OutcomeLaunchIntake(objective="Build it"))

    assert plan.runnable is False
    assert plan.next_action == "collect_missing_answers"
    assert [question.id for question in plan.missing_answers] == [
        "clarify-objective",
        "name-project",
        "capture-constraints",
        "resolve-model",
    ]
    assert plan.plan_preview.workflow_id == "github.pr-review"
    assert plan.plan_preview.workflow_name == "github-pr-review"
    assert plan.plan_preview.task_class == "coding"
    assert plan.plan_preview.model_routing_path == "/v1/model-health/task-routing"
    assert plan.plan_preview.evidence_required == [
        "inspect-thread-state",
        "review-diff",
        "recommend-merge-plan",
    ]


def test_build_guided_launch_plan_returns_runnable_dry_run_for_complete_intake() -> None:
    plan = build_guided_launch_plan(
        OutcomeLaunchIntake(
            objective="Research competitor pricing and summarize risks",
            project_name="market scan",
            preferred_model="openrouter/auto",
            constraints=["finish under one hour", "no browser mutation"],
        )
    )

    assert plan.runnable is True
    assert plan.next_action == "run_dry_preview"
    assert plan.missing_answers == []
    assert plan.plan_preview.workflow_id == "github.issue-triage"
    assert plan.plan_preview.task_class == "research"
    assert plan.plan_preview.dry_run is True
