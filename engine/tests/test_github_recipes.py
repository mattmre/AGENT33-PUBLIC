from __future__ import annotations

from agent33.workflows.github_recipes import (
    build_changelog_recipe,
    build_ci_repair_recipe,
    build_issue_triage_recipe,
    build_pr_review_recipe,
    build_release_readiness_recipe,
)


def test_pr_review_recipe_captures_review_first_flow() -> None:
    recipe = build_pr_review_recipe()

    assert recipe.recipe_id == "github.pr-review"
    assert recipe.inputs["pull_request"] == "Pull request number or URL"
    assert recipe.required_evidence_steps() == ["collect-context", "review-risk"]
    assert recipe.steps[0].required_tools == ["github"]


def test_ci_repair_recipe_captures_failure_to_fix_flow() -> None:
    recipe = build_ci_repair_recipe()

    assert recipe.recipe_id == "github.ci-repair"
    assert recipe.inputs["run_id"] == "Failed workflow run ID"
    assert recipe.required_evidence_steps() == [
        "inspect-failure",
        "patch-targeted-fix",
        "rerun-local-validation",
    ]
    assert recipe.steps[1].required_tools == ["apply_patch"]


def test_release_readiness_recipe_reports_blockers() -> None:
    recipe = build_release_readiness_recipe()

    assert recipe.recipe_id == "github.release-readiness"
    assert recipe.inputs["release_ref"] == "Release branch, tag, or commit"
    assert recipe.required_evidence_steps() == [
        "check-status",
        "verify-artifacts",
        "report-blockers",
    ]
    assert recipe.escalation_paths == ["release-owner-review"]


def test_issue_triage_recipe_collects_query_scope() -> None:
    recipe = build_issue_triage_recipe()

    assert recipe.recipe_id == "github.issue-triage"
    assert recipe.inputs["issue_query"] == "Issue search query"
    assert recipe.steps[0].required_tools == ["github"]
    assert recipe.outputs["triage_plan"] == "Labels, priority, owner, and next action"


def test_changelog_recipe_groups_user_facing_changes() -> None:
    recipe = build_changelog_recipe()

    assert recipe.recipe_id == "github.changelog"
    assert recipe.inputs["range"] == "Commit or PR range"
    assert recipe.required_evidence_steps() == [
        "collect-merged-prs",
        "group-user-facing-changes",
        "draft-changelog",
    ]
