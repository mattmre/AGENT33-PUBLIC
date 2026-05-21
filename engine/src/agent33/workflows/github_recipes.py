"""GitHub workflow recipe library."""

from __future__ import annotations

from agent33.workflows.recipes import WorkflowRecipe, WorkflowRecipeStep


def build_pr_review_recipe() -> WorkflowRecipe:
    return WorkflowRecipe(
        recipe_id="github.pr-review",
        version="1.0.0",
        title="GitHub PR Review",
        inputs={"pull_request": "Pull request number or URL"},
        outputs={"findings": "Ordered review findings with file references"},
        steps=[
            WorkflowRecipeStep(
                step_id="collect-context",
                title="Collect diff, comments, and checks",
                policy="review_only",
                required_tools=["github"],
            ),
            WorkflowRecipeStep(
                step_id="review-risk",
                title="Review for regressions, missing tests, and unsafe behavior",
                policy="review_only",
            ),
            WorkflowRecipeStep(
                step_id="report-findings",
                title="Report actionable findings first",
                policy="review_only",
                evidence_required=False,
            ),
        ],
        escalation_paths=["request-human-review"],
    )


def build_ci_repair_recipe() -> WorkflowRecipe:
    return WorkflowRecipe(
        recipe_id="github.ci-repair",
        version="1.0.0",
        title="GitHub CI Repair",
        inputs={
            "pull_request": "Pull request number or URL",
            "run_id": "Failed workflow run ID",
        },
        outputs={"fix_summary": "Applied fix and validation evidence"},
        steps=[
            WorkflowRecipeStep(
                step_id="inspect-failure",
                title="Inspect failing checks and logs",
                policy="review_only",
                required_tools=["github"],
            ),
            WorkflowRecipeStep(
                step_id="patch-targeted-fix",
                title="Patch the smallest failing surface",
                policy="approval_required",
                required_tools=["apply_patch"],
            ),
            WorkflowRecipeStep(
                step_id="rerun-local-validation",
                title="Run focused local validation",
                policy="approval_required",
            ),
        ],
        escalation_paths=["request-human-review"],
    )


def build_release_readiness_recipe() -> WorkflowRecipe:
    return WorkflowRecipe(
        recipe_id="github.release-readiness",
        version="1.0.0",
        title="GitHub Release Readiness",
        inputs={"release_ref": "Release branch, tag, or commit"},
        outputs={"readiness_report": "Release readiness report with blockers"},
        steps=[
            WorkflowRecipeStep(
                step_id="check-status",
                title="Check branch, tests, and pending PRs",
                policy="review_only",
                required_tools=["github"],
            ),
            WorkflowRecipeStep(
                step_id="verify-artifacts",
                title="Verify changelog, docs, and release artifacts",
                policy="review_only",
            ),
            WorkflowRecipeStep(
                step_id="report-blockers",
                title="Report release blockers and go/no-go decision",
                policy="review_only",
            ),
        ],
        escalation_paths=["release-owner-review"],
    )


def build_issue_triage_recipe() -> WorkflowRecipe:
    return WorkflowRecipe(
        recipe_id="github.issue-triage",
        version="1.0.0",
        title="GitHub Issue Triage",
        inputs={"issue_query": "Issue search query"},
        outputs={"triage_plan": "Labels, priority, owner, and next action"},
        steps=[
            WorkflowRecipeStep(
                step_id="collect-issues",
                title="Collect matching issues and current labels",
                policy="review_only",
                required_tools=["github"],
            ),
            WorkflowRecipeStep(
                step_id="categorize",
                title="Categorize by severity, owner, and actionability",
                policy="review_only",
            ),
            WorkflowRecipeStep(
                step_id="report-next-actions",
                title="Report triage actions",
                policy="review_only",
            ),
        ],
        escalation_paths=["maintainer-triage"],
    )


def build_changelog_recipe() -> WorkflowRecipe:
    return WorkflowRecipe(
        recipe_id="github.changelog",
        version="1.0.0",
        title="GitHub Changelog",
        inputs={"range": "Commit or PR range"},
        outputs={"changelog": "Grouped changelog entries"},
        steps=[
            WorkflowRecipeStep(
                step_id="collect-merged-prs",
                title="Collect merged PRs and commits",
                policy="review_only",
                required_tools=["github"],
            ),
            WorkflowRecipeStep(
                step_id="group-user-facing-changes",
                title="Group user-facing changes",
                policy="review_only",
            ),
            WorkflowRecipeStep(
                step_id="draft-changelog",
                title="Draft changelog entries",
                policy="review_only",
            ),
        ],
        escalation_paths=["release-owner-review"],
    )
