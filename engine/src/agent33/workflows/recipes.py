"""Workflow recipe contract."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent33.workflows.definition import (
    ParameterDef,
    StepAction,
    WorkflowDefinition,
    WorkflowExecution,
    WorkflowMetadata,
    WorkflowStep,
)


class WorkflowRecipeStep(BaseModel):
    step_id: str
    title: str
    policy: str = ""
    model_hint: str = ""
    required_tools: list[str] = Field(default_factory=list)
    evidence_required: bool = True


class WorkflowRecipe(BaseModel):
    recipe_id: str
    version: str
    title: str
    inputs: dict[str, str] = Field(default_factory=dict)
    outputs: dict[str, str] = Field(default_factory=dict)
    steps: list[WorkflowRecipeStep] = Field(default_factory=list)
    escalation_paths: list[str] = Field(default_factory=list)

    def required_evidence_steps(self) -> list[str]:
        return [step.step_id for step in self.steps if step.evidence_required]

    def to_workflow_definition(self, *, dry_run: bool = True) -> WorkflowDefinition:
        """Convert this recipe into an executable workflow definition skeleton."""
        workflow_steps: list[WorkflowStep] = []
        previous_step_id = ""
        for step in self.steps:
            workflow_step = WorkflowStep(
                id=step.step_id,
                name=step.title,
                action=StepAction.VALIDATE,
                depends_on=[previous_step_id] if previous_step_id else [],
                inputs={
                    "policy": step.policy,
                    "model_hint": step.model_hint,
                    "required_tools": step.required_tools,
                    "evidence_required": step.evidence_required,
                },
                outputs={"evidence": step.evidence_required},
            )
            workflow_steps.append(workflow_step)
            previous_step_id = step.step_id

        return WorkflowDefinition(
            name=self.recipe_id.replace(".", "-").replace("_", "-"),
            version=self.version,
            description=self.title,
            inputs={
                key: ParameterDef(type="string", description=value, required=True)
                for key, value in self.inputs.items()
            },
            outputs={
                key: ParameterDef(type="string", description=value)
                for key, value in self.outputs.items()
            },
            steps=workflow_steps,
            execution=WorkflowExecution(dry_run=dry_run),
            metadata=WorkflowMetadata(
                author="AGENT33 recipe library",
                tags=["recipe", self.recipe_id],
            ),
        )

    def execution_preview(self) -> dict[str, object]:
        """Return a UI/API-friendly preview of the generated run plan."""
        workflow = self.to_workflow_definition(dry_run=True)
        step_previews = []
        dependency_graph: dict[str, list[str]] = {}
        for index, step in enumerate(workflow.steps, start=1):
            required_tools = list(step.inputs.get("required_tools", []))
            evidence_required = bool(step.inputs.get("evidence_required", False))
            depends_on = list(step.depends_on)
            dependency_graph[step.id] = depends_on
            step_previews.append(
                {
                    "id": step.id,
                    "title": step.name or step.id,
                    "sequence": index,
                    "depends_on": depends_on,
                    "required_tools": required_tools,
                    "policy": step.inputs.get("policy", ""),
                    "model_hint": step.inputs.get("model_hint", ""),
                    "evidence_required": evidence_required,
                    "evidence_prompt": _evidence_prompt(
                        step.name or step.id,
                        required_tools,
                        evidence_required,
                    ),
                }
            )
        return {
            "recipe_id": self.recipe_id,
            "workflow_name": workflow.name,
            "dry_run": workflow.execution.dry_run,
            "required_evidence_steps": self.required_evidence_steps(),
            "operator_summary": _operator_summary(self),
            "dependency_graph": dependency_graph,
            "steps": step_previews,
            "blockers": _preview_blockers(self),
        }


def github_recipe_library() -> list[WorkflowRecipe]:
    return [
        WorkflowRecipe(
            recipe_id="github.pr-review",
            version="1.0.0",
            title="GitHub PR Review",
            inputs={"pr_url": "Pull request URL or number"},
            outputs={"review_summary": "Actionable review findings and merge recommendation"},
            steps=[
                WorkflowRecipeStep(
                    step_id="inspect-thread-state",
                    title="Inspect unresolved review threads",
                    policy="read-only GitHub inspection",
                    model_hint="reviewer",
                    required_tools=["github.pr.view", "github.review_threads"],
                ),
                WorkflowRecipeStep(
                    step_id="review-diff",
                    title="Review changed files and tests",
                    policy="read-only repository inspection",
                    model_hint="reviewer",
                    required_tools=["git.diff", "pytest"],
                ),
                WorkflowRecipeStep(
                    step_id="recommend-merge-plan",
                    title="Recommend fix or merge plan",
                    policy="summarize evidence before mutation",
                    model_hint="senior-reviewer",
                ),
            ],
            escalation_paths=["human-review", "security-review"],
        ),
        WorkflowRecipe(
            recipe_id="github.ci-repair",
            version="1.0.0",
            title="GitHub CI Repair",
            inputs={"run_url": "Failing GitHub Actions run or PR number"},
            outputs={"fix_summary": "Patch summary and validation commands"},
            steps=[
                WorkflowRecipeStep(
                    step_id="inspect-failing-jobs",
                    title="Inspect failing jobs and logs",
                    policy="read-only CI inspection",
                    model_hint="debugger",
                    required_tools=["github.actions.logs"],
                ),
                WorkflowRecipeStep(
                    step_id="patch-failure",
                    title="Patch the failing layer",
                    policy="scoped repository mutation",
                    model_hint="worker",
                    required_tools=["git.apply_patch"],
                ),
                WorkflowRecipeStep(
                    step_id="validate-fix",
                    title="Run focused validation",
                    policy="local validation before merge",
                    model_hint="validator",
                    required_tools=["pytest", "ruff"],
                ),
            ],
            escalation_paths=["human-review"],
        ),
        WorkflowRecipe(
            recipe_id="github.release-readiness",
            version="1.0.0",
            title="GitHub Release Readiness",
            inputs={"release_ref": "Branch, tag, or milestone to prepare"},
            outputs={"release_report": "Release gate status and remaining blockers"},
            steps=[
                WorkflowRecipeStep(
                    step_id="collect-release-scope",
                    title="Collect release scope and changed surfaces",
                    policy="read-only release inspection",
                    model_hint="release-manager",
                    required_tools=["git.log", "github.milestones"],
                ),
                WorkflowRecipeStep(
                    step_id="verify-release-gates",
                    title="Verify release gates",
                    policy="local validation and security checks",
                    model_hint="validator",
                    required_tools=["pytest", "ruff", "npm.audit"],
                ),
                WorkflowRecipeStep(
                    step_id="write-release-report",
                    title="Write release readiness report",
                    policy="evidence-backed reporting",
                    model_hint="release-manager",
                ),
            ],
            escalation_paths=["release-owner"],
        ),
        WorkflowRecipe(
            recipe_id="github.issue-triage",
            version="1.0.0",
            title="GitHub Issue Triage",
            inputs={"issue_query": "Issue URL, number, label, or search query"},
            outputs={"triage_summary": "Priority, owner, reproduction state, and next action"},
            steps=[
                WorkflowRecipeStep(
                    step_id="classify-issues",
                    title="Classify issues by impact and freshness",
                    policy="read-only issue inspection",
                    model_hint="triager",
                    required_tools=["github.issues.search"],
                ),
                WorkflowRecipeStep(
                    step_id="map-to-roadmap",
                    title="Map issues to roadmap and owners",
                    policy="read-only planning inspection",
                    model_hint="planner",
                    required_tools=["git.rg"],
                ),
                WorkflowRecipeStep(
                    step_id="recommend-next-actions",
                    title="Recommend next actions",
                    policy="operator approval before mutation",
                    model_hint="triager",
                ),
            ],
            escalation_paths=["product-owner"],
        ),
        WorkflowRecipe(
            recipe_id="github.changelog-prep",
            version="1.0.0",
            title="GitHub Changelog Preparation",
            inputs={"range": "Commit range or release branch"},
            outputs={"changelog_draft": "Grouped changelog draft with source commits"},
            steps=[
                WorkflowRecipeStep(
                    step_id="collect-commits",
                    title="Collect commits and merged PRs",
                    policy="read-only git/GitHub inspection",
                    model_hint="release-writer",
                    required_tools=["git.log", "github.pr.list"],
                ),
                WorkflowRecipeStep(
                    step_id="group-changes",
                    title="Group changes by operator-facing impact",
                    policy="read-only synthesis",
                    model_hint="release-writer",
                ),
                WorkflowRecipeStep(
                    step_id="draft-changelog",
                    title="Draft changelog update",
                    policy="scoped documentation mutation",
                    model_hint="docs-worker",
                    required_tools=["git.apply_patch"],
                ),
            ],
            escalation_paths=["release-owner"],
        ),
    ]


def get_github_recipe(recipe_id: str) -> WorkflowRecipe | None:
    for recipe in github_recipe_library():
        if recipe.recipe_id == recipe_id:
            return recipe
    return None


def _operator_summary(recipe: WorkflowRecipe) -> str:
    return (
        f"{recipe.title}: {len(recipe.steps)} dry-run steps, "
        f"{len(recipe.required_evidence_steps())} evidence gate(s), "
        f"{len(recipe.escalation_paths)} escalation path(s)."
    )


def _evidence_prompt(title: str, required_tools: list[str], evidence_required: bool) -> str:
    if not evidence_required:
        return "Evidence optional; summarize decision rationale before continuing."
    if required_tools:
        return f"Capture output from {', '.join(required_tools)} for '{title}'."
    return f"Capture a concise evidence note for '{title}'."


def _preview_blockers(recipe: WorkflowRecipe) -> list[str]:
    blockers: list[str] = []
    if not recipe.steps:
        blockers.append("Recipe has no execution steps.")
    for step in recipe.steps:
        if step.evidence_required and not step.required_tools and not step.policy:
            blockers.append(
                f"Step '{step.step_id}' requires evidence but has no tool or policy hint."
            )
    return blockers
