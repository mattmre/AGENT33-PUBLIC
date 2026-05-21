"""Outcome launch recommendation contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from agent33.workflows.recipes import get_github_recipe


class LaunchScale(StrEnum):
    QUICK_TASK = "quick_task"
    PROJECT_BUILD = "project_build"
    RESEARCH_WORKFLOW = "research_workflow"
    IMPROVEMENT_LOOP = "improvement_loop"
    LONG_RUNNING_PROGRAM = "long_running_program"


class OutcomeLaunchIntake(BaseModel):
    objective: str = Field(min_length=1)
    project_name: str = ""
    preferred_runtime: str = "agent-os"
    preferred_model: str = "recommended"
    constraints: list[str] = Field(default_factory=list)


class OutcomeLaunchRecommendation(BaseModel):
    scale: LaunchScale
    recommended_workflow: str
    recommended_pack: str
    recommended_model: str
    recommended_runtime: str
    preview_steps: list[str] = Field(default_factory=list)


LaunchFrictionSeverity = Literal["info", "warning", "blocker"]
LaunchReadiness = Literal["ready", "needs_input", "blocked"]


class LaunchFrictionSignal(BaseModel):
    id: str
    severity: LaunchFrictionSeverity
    message: str
    fix_action: str
    step: str
    points: int = Field(ge=0, le=100)


class OutcomeLaunchFrictionEvaluation(BaseModel):
    recommendation: OutcomeLaunchRecommendation
    friction_score: int = Field(ge=0, le=100)
    readiness: LaunchReadiness
    signals: list[LaunchFrictionSignal] = Field(default_factory=list)


class GuidedLaunchQuestion(BaseModel):
    id: str
    prompt: str
    field: str
    reason: str
    required: bool = True


class GuidedLaunchPlanPreview(BaseModel):
    workflow_name: str
    workflow_id: str
    dry_run: bool
    task_class: str
    model_routing_path: str
    runtime: str
    pack: str
    steps: list[dict[str, object]] = Field(default_factory=list)
    approvals_required: list[str] = Field(default_factory=list)
    evidence_required: list[str] = Field(default_factory=list)


class GuidedLaunchPlan(BaseModel):
    intake: OutcomeLaunchIntake
    evaluation: OutcomeLaunchFrictionEvaluation
    missing_answers: list[GuidedLaunchQuestion] = Field(default_factory=list)
    plan_preview: GuidedLaunchPlanPreview
    runnable: bool
    next_action: str


def recommend_outcome_launch(intake: OutcomeLaunchIntake) -> OutcomeLaunchRecommendation:
    objective = intake.objective.lower()
    if "research" in objective or "competitor" in objective:
        scale = LaunchScale.RESEARCH_WORKFLOW
        workflow = "github.issue-triage"
        pack = "research-brief"
    elif "improve" in objective or "loop" in objective:
        scale = LaunchScale.IMPROVEMENT_LOOP
        workflow = "github.release-readiness"
        pack = "improvement-loop"
    elif "build" in objective or "project" in objective or intake.project_name:
        scale = LaunchScale.PROJECT_BUILD
        workflow = "github.pr-review"
        pack = "project-build"
    else:
        scale = LaunchScale.QUICK_TASK
        workflow = "github.ci-repair"
        pack = "quick-fix"

    return OutcomeLaunchRecommendation(
        scale=scale,
        recommended_workflow=workflow,
        recommended_pack=pack,
        recommended_model=intake.preferred_model,
        recommended_runtime=intake.preferred_runtime,
        preview_steps=[
            "confirm objective and constraints",
            "prepare dry-run workflow plan",
            "check runtime and model readiness",
            "request approval before mutating project files",
        ],
    )


def evaluate_outcome_launch_friction(
    intake: OutcomeLaunchIntake,
) -> OutcomeLaunchFrictionEvaluation:
    """Score launch friction from the actual outcome launch intake."""
    recommendation = recommend_outcome_launch(intake)
    objective_words = [word for word in intake.objective.strip().split() if word]
    constraints = [constraint.strip() for constraint in intake.constraints if constraint.strip()]
    signals: list[LaunchFrictionSignal] = []

    if len(objective_words) < 4:
        signals.append(
            LaunchFrictionSignal(
                id="objective-too-thin",
                severity="warning",
                message="The objective is too short to generate a reliable run plan.",
                fix_action="Ask one clarifying question before previewing the run.",
                step="confirm objective and constraints",
                points=25,
            )
        )

    if (
        recommendation.scale
        in {
            LaunchScale.PROJECT_BUILD,
            LaunchScale.LONG_RUNNING_PROGRAM,
        }
        and not intake.project_name.strip()
    ):
        signals.append(
            LaunchFrictionSignal(
                id="missing-project-context",
                severity="warning",
                message="Project-scale work needs a named project or workspace.",
                fix_action="Collect or create the project name before launch.",
                step="confirm objective and constraints",
                points=15,
            )
        )

    if not constraints:
        signals.append(
            LaunchFrictionSignal(
                id="missing-constraints",
                severity="info",
                message=(
                    "No constraints are captured for budget, safety, timing, or success criteria."
                ),
                fix_action="Prompt for at least one launch constraint.",
                step="confirm objective and constraints",
                points=10,
            )
        )

    if intake.preferred_model.strip() in {"", "recommended"}:
        signals.append(
            LaunchFrictionSignal(
                id="model-not-selected",
                severity="warning",
                message="The model is still generic, so task-to-model readiness is not auditable.",
                fix_action="Resolve the recommended model before execution.",
                step="check runtime and model readiness",
                points=15,
            )
        )

    if intake.preferred_runtime.strip().lower() != "agent-os":
        signals.append(
            LaunchFrictionSignal(
                id="non-default-runtime",
                severity="warning",
                message="The launch path is not using the default governed Agent OS runtime.",
                fix_action="Show the runtime risk and require explicit operator confirmation.",
                step="check runtime and model readiness",
                points=15,
            )
        )

    friction_score = min(100, sum(signal.points for signal in signals))
    blocker_present = any(signal.severity == "blocker" for signal in signals)
    readiness: LaunchReadiness
    if blocker_present or friction_score >= 60:
        readiness = "blocked"
    elif friction_score:
        readiness = "needs_input"
    else:
        readiness = "ready"

    return OutcomeLaunchFrictionEvaluation(
        recommendation=recommendation,
        friction_score=friction_score,
        readiness=readiness,
        signals=signals,
    )


def build_guided_launch_plan(intake: OutcomeLaunchIntake) -> GuidedLaunchPlan:
    """Build a guided intake-to-plan preview from the live outcome launch contract."""
    evaluation = evaluate_outcome_launch_friction(intake)
    recommendation = evaluation.recommendation
    missing_answers = _missing_guided_answers(intake, evaluation)
    recipe = get_github_recipe(recommendation.recommended_workflow)
    workflow_preview = recipe.execution_preview() if recipe is not None else {}
    raw_step_previews = workflow_preview.get("steps", [])
    step_previews = raw_step_previews if isinstance(raw_step_previews, list) else []
    evidence_required = [
        str(step["id"])
        for step in step_previews
        if isinstance(step, dict) and step.get("evidence_required") is True
    ]
    approvals_required = ["file_mutation_approval"]
    if recommendation.recommended_runtime != "agent-os":
        approvals_required.append("runtime_override_approval")

    plan_preview = GuidedLaunchPlanPreview(
        workflow_name=str(workflow_preview.get("workflow_name") or ""),
        workflow_id=recommendation.recommended_workflow,
        dry_run=bool(workflow_preview.get("dry_run", True)),
        task_class=_task_class_for_scale(recommendation.scale),
        model_routing_path="/v1/model-health/task-routing",
        runtime=recommendation.recommended_runtime,
        pack=recommendation.recommended_pack,
        steps=step_previews,
        approvals_required=approvals_required,
        evidence_required=evidence_required,
    )
    runnable = evaluation.readiness == "ready" and not missing_answers and bool(step_previews)
    return GuidedLaunchPlan(
        intake=intake,
        evaluation=evaluation,
        missing_answers=missing_answers,
        plan_preview=plan_preview,
        runnable=runnable,
        next_action=("run_dry_preview" if runnable else "collect_missing_answers"),
    )


def _missing_guided_answers(
    intake: OutcomeLaunchIntake,
    evaluation: OutcomeLaunchFrictionEvaluation,
) -> list[GuidedLaunchQuestion]:
    questions: list[GuidedLaunchQuestion] = []
    signal_ids = {signal.id for signal in evaluation.signals}
    if "objective-too-thin" in signal_ids:
        questions.append(
            GuidedLaunchQuestion(
                id="clarify-objective",
                field="objective",
                prompt=(
                    "What outcome should AGENT33 produce, and what should be true when it is done?"
                ),
                reason="The objective is too short to produce a reliable run plan.",
            )
        )
    if "missing-project-context" in signal_ids:
        questions.append(
            GuidedLaunchQuestion(
                id="name-project",
                field="project_name",
                prompt="What project or workspace should this work belong to?",
                reason=(
                    "Project-scale work needs a stable project name for recovery and artifacts."
                ),
            )
        )
    if "missing-constraints" in signal_ids:
        questions.append(
            GuidedLaunchQuestion(
                id="capture-constraints",
                field="constraints",
                prompt=(
                    "What constraints should the run respect for time, budget, safety, or quality?"
                ),
                reason="Constraints become approval and validation checks before execution.",
            )
        )
    if "model-not-selected" in signal_ids or intake.preferred_model.strip() in {"", "recommended"}:
        questions.append(
            GuidedLaunchQuestion(
                id="resolve-model",
                field="preferred_model",
                prompt=(
                    "Should AGENT33 use the recommended ready model or a specific provider/model?"
                ),
                reason="The preview must route through auditable task-to-model readiness.",
                required=False,
            )
        )
    return questions


def _task_class_for_scale(scale: LaunchScale) -> str:
    return {
        LaunchScale.QUICK_TASK: "quick_task",
        LaunchScale.PROJECT_BUILD: "coding",
        LaunchScale.RESEARCH_WORKFLOW: "research",
        LaunchScale.IMPROVEMENT_LOOP: "long_context",
        LaunchScale.LONG_RUNNING_PROGRAM: "long_context",
    }[scale]
