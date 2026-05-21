from __future__ import annotations

from agent33.workflows.recipes import (
    WorkflowRecipe,
    WorkflowRecipeStep,
    get_github_recipe,
    github_recipe_library,
)


def test_workflow_recipe_tracks_required_evidence_steps() -> None:
    recipe = WorkflowRecipe(
        recipe_id="recipe.pr-review",
        version="1.0.0",
        title="PR Review",
        inputs={"pr": "Pull request number"},
        outputs={"summary": "Review summary"},
        steps=[
            WorkflowRecipeStep(step_id="inspect", title="Inspect diff"),
            WorkflowRecipeStep(step_id="summarize", title="Summarize", evidence_required=False),
        ],
        escalation_paths=["human-review"],
    )

    assert recipe.required_evidence_steps() == ["inspect"]
    assert recipe.inputs["pr"] == "Pull request number"


def test_workflow_recipe_converts_to_dry_run_workflow_definition() -> None:
    recipe = WorkflowRecipe(
        recipe_id="recipe.pr-review",
        version="1.0.0",
        title="PR Review",
        inputs={"pr": "Pull request number"},
        outputs={"summary": "Review summary"},
        steps=[
            WorkflowRecipeStep(
                step_id="inspect",
                title="Inspect diff",
                policy="read-only",
                model_hint="reviewer",
                required_tools=["github.pr.diff"],
            ),
            WorkflowRecipeStep(step_id="summarize", title="Summarize"),
        ],
    )

    workflow = recipe.to_workflow_definition()

    assert workflow.name == "recipe-pr-review"
    assert workflow.execution.dry_run is True
    assert workflow.inputs["pr"].required is True
    assert workflow.outputs["summary"].description == "Review summary"
    assert [step.id for step in workflow.steps] == ["inspect", "summarize"]
    assert workflow.steps[1].depends_on == ["inspect"]
    assert workflow.steps[0].inputs["required_tools"] == ["github.pr.diff"]


def test_workflow_recipe_execution_preview_exposes_evidence_and_dependencies() -> None:
    recipe = WorkflowRecipe(
        recipe_id="recipe.ci-repair",
        version="1.0.0",
        title="CI Repair",
        steps=[
            WorkflowRecipeStep(step_id="inspect", title="Inspect failing checks"),
            WorkflowRecipeStep(
                step_id="patch",
                title="Patch failure",
                required_tools=["git.apply_patch"],
                evidence_required=False,
            ),
        ],
    )

    preview = recipe.execution_preview()

    assert preview["workflow_name"] == "recipe-ci-repair"
    assert preview["required_evidence_steps"] == ["inspect"]
    assert preview["steps"][1]["depends_on"] == ["inspect"]
    assert preview["steps"][1]["required_tools"] == ["git.apply_patch"]
    assert preview["steps"][1]["evidence_required"] is False
    assert preview["operator_summary"] == (
        "CI Repair: 2 dry-run steps, 1 evidence gate(s), 0 escalation path(s)."
    )
    assert preview["dependency_graph"] == {"inspect": [], "patch": ["inspect"]}
    assert "Capture a concise evidence note" in preview["steps"][0]["evidence_prompt"]
    assert preview["blockers"] == [
        "Step 'inspect' requires evidence but has no tool or policy hint."
    ]


def test_workflow_recipe_preview_uses_tool_evidence_prompt() -> None:
    recipe = get_github_recipe("github.ci-repair")

    assert recipe is not None
    preview = recipe.execution_preview()

    inspect_step = preview["steps"][0]
    assert "github.actions.logs" in inspect_step["evidence_prompt"]
    assert inspect_step["policy"] == "read-only CI inspection"
    assert preview["blockers"] == []


def test_github_recipe_library_contains_runnable_starter_recipes() -> None:
    recipes = github_recipe_library()

    assert {recipe.recipe_id for recipe in recipes} == {
        "github.pr-review",
        "github.ci-repair",
        "github.release-readiness",
        "github.issue-triage",
        "github.changelog-prep",
    }
    assert all(recipe.steps for recipe in recipes)
    assert all(recipe.required_evidence_steps() for recipe in recipes)
    assert all(recipe.to_workflow_definition().execution.dry_run for recipe in recipes)


def test_get_github_recipe_returns_catalog_entry() -> None:
    recipe = get_github_recipe("github.ci-repair")

    assert recipe is not None
    assert recipe.title == "GitHub CI Repair"
    assert recipe.execution_preview()["steps"][0]["id"] == "inspect-failing-jobs"
