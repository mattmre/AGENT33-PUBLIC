import type { DomainConfig } from "../../types";

export const explanationsDomain: DomainConfig = {
  id: "explanations",
  title: "Explanations",
  description: "Generate and manage explanations with fact-check validation.",
  operations: [
    {
      id: "explanations-create",
      title: "Create Explanation",
      method: "POST",
      path: "/v1/explanations/",
      description: "Generate a new explanation for an entity.",
      defaultBody: JSON.stringify(
        {
          entity_type: "workflow",
          entity_id: "hello-flow",
          mode: "plan_review",
          metadata: {
            model: "llama3.1",
            highlights: ["Review generated plan and constraints"]
          },
          claims: [
            {
              claim_type: "metadata_equals",
              target: "model",
              expected: "llama3.1",
              description: "Expected model metadata must be preserved"
            }
          ]
        },
        null,
        2
      )
    },
    {
      id: "explanations-get",
      title: "Get Explanation",
      method: "GET",
      path: "/v1/explanations/{explanation_id}",
      description: "Retrieve an explanation by ID.",
      defaultPathParams: {
        explanation_id: "expl-abc123"
      }
    },
    {
      id: "explanations-list",
      title: "List Explanations",
      method: "GET",
      path: "/v1/explanations/",
      description: "List all explanations with optional filters."
    },
    {
      id: "explanations-list-by-entity",
      title: "List by Entity",
      method: "GET",
      path: "/v1/explanations/",
      description: "List explanations filtered by entity.",
      defaultQuery: {
        entity_type: "workflow",
        entity_id: "hello-flow"
      }
    },
    {
      id: "explanations-delete",
      title: "Delete Explanation",
      method: "DELETE",
      path: "/v1/explanations/{explanation_id}",
      description: "Delete an explanation.",
      defaultPathParams: {
        explanation_id: "expl-abc123"
      }
    },
    {
      id: "explanations-rerun-fact-check",
      title: "Re-run Fact Check",
      method: "POST",
      path: "/v1/explanations/{explanation_id}/fact-check",
      description: "Re-run deterministic fact-check validation.",
      defaultPathParams: {
        explanation_id: "expl-abc123"
      }
    },
    {
      id: "explanations-claims",
      title: "Get Claims",
      method: "GET",
      path: "/v1/explanations/{explanation_id}/claims",
      description: "Retrieve claim-level fact-check details.",
      defaultPathParams: {
        explanation_id: "expl-abc123"
      }
    },
    {
      id: "explanations-diff-review",
      title: "Diff Review",
      method: "POST",
      path: "/v1/explanations/diff-review",
      description: "Generate an HTML explanation from a code diff.",
      uxHint: "explanation-html",
      defaultBody: JSON.stringify(
        {
          entity_type: "pull-request",
          entity_id: "pr-42",
          diff_text: "--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-old line\n+new line",
          metadata: {},
          claims: []
        },
        null,
        2
      )
    },
    {
      id: "explanations-plan-review",
      title: "Plan Review",
      method: "POST",
      path: "/v1/explanations/plan-review",
      description: "Generate an HTML explanation from a plan document.",
      uxHint: "explanation-html",
      defaultBody: JSON.stringify(
        {
          entity_type: "workflow",
          entity_id: "hello-flow",
          plan_text: "## Plan\n- Step 1: Review constraints\n- Step 2: Validate outputs",
          metadata: {},
          claims: []
        },
        null,
        2
      )
    },
    {
      id: "explanations-project-recap",
      title: "Project Recap",
      method: "POST",
      path: "/v1/explanations/project-recap",
      description: "Generate an HTML explanation summarising a project milestone.",
      uxHint: "explanation-html",
      defaultBody: JSON.stringify(
        {
          entity_type: "project",
          entity_id: "agent33",
          recap_text: "Phase 26 delivered HTML preview and three new explanation endpoints.",
          highlights: [
            "Diff review endpoint added",
            "Plan review endpoint added",
            "Project recap endpoint added"
          ],
          metadata: {},
          claims: []
        },
        null,
        2
      )
    }
  ]
};
