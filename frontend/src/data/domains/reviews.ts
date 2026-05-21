import type { DomainConfig } from "../../types";

export const reviewsDomain: DomainConfig = {
  id: "reviews",
  title: "Reviews",
  description: "Two-layer review lifecycle.",
  operations: [
    {
      id: "reviews-create",
      title: "Create Review",
      method: "POST",
      path: "/v1/reviews/",
      description: "Start a review record.",
      defaultBody: JSON.stringify(
        {
          task_id: "TASK-101",
          branch: "feat/ui-phase22",
          pr_number: 22
        },
        null,
        2
      )
    },
    {
      id: "reviews-list",
      title: "List Reviews",
      method: "GET",
      path: "/v1/reviews/",
      description: "List reviews."
    },
    {
      id: "reviews-get",
      title: "Get Review",
      method: "GET",
      path: "/v1/reviews/{review_id}",
      description: "Get review detail.",
      defaultPathParams: {
        review_id: "replace-with-review-id"
      }
    },
    {
      id: "reviews-delete",
      title: "Delete Review",
      method: "DELETE",
      path: "/v1/reviews/{review_id}",
      description: "Delete review entry.",
      defaultPathParams: {
        review_id: "replace-with-review-id"
      }
    },
    {
      id: "reviews-assess",
      title: "Assess Review",
      method: "POST",
      path: "/v1/reviews/{review_id}/assess",
      description: "Run risk assessment.",
      defaultPathParams: {
        review_id: "replace-with-review-id"
      },
      defaultBody: JSON.stringify({ triggers: ["security", "api-public"] }, null, 2)
    },
    {
      id: "reviews-ready",
      title: "Mark Ready",
      method: "POST",
      path: "/v1/reviews/{review_id}/ready",
      description: "Transition to ready.",
      defaultPathParams: {
        review_id: "replace-with-review-id"
      },
      defaultBody: "{}"
    },
    {
      id: "reviews-assign-l1",
      title: "Assign L1",
      method: "POST",
      path: "/v1/reviews/{review_id}/assign-l1",
      description: "Assign L1 reviewer.",
      defaultPathParams: {
        review_id: "replace-with-review-id"
      },
      defaultBody: "{}"
    },
    {
      id: "reviews-l1",
      title: "L1 Decision",
      method: "POST",
      path: "/v1/reviews/{review_id}/l1",
      description: "Submit L1 decision.",
      defaultPathParams: {
        review_id: "replace-with-review-id"
      },
      defaultBody: JSON.stringify(
        {
          decision: "approved",
          issues: [],
          comments: "L1 pass"
        },
        null,
        2
      )
    },
    {
      id: "reviews-assign-l2",
      title: "Assign L2",
      method: "POST",
      path: "/v1/reviews/{review_id}/assign-l2",
      description: "Assign L2 reviewer.",
      defaultPathParams: {
        review_id: "replace-with-review-id"
      },
      defaultBody: "{}"
    },
    {
      id: "reviews-l2",
      title: "L2 Decision",
      method: "POST",
      path: "/v1/reviews/{review_id}/l2",
      description: "Submit L2 decision.",
      defaultPathParams: {
        review_id: "replace-with-review-id"
      },
      defaultBody: JSON.stringify(
        {
          decision: "approved",
          issues: [],
          comments: "L2 pass"
        },
        null,
        2
      )
    },
    {
      id: "reviews-approve",
      title: "Approve Review",
      method: "POST",
      path: "/v1/reviews/{review_id}/approve",
      description: "Final approval.",
      defaultPathParams: {
        review_id: "replace-with-review-id"
      },
      defaultBody: JSON.stringify(
        {
          conditions: []
        },
        null,
        2
      )
    },
    {
      id: "reviews-merge",
      title: "Merge Review",
      method: "POST",
      path: "/v1/reviews/{review_id}/merge",
      description: "Finalize merge action.",
      defaultPathParams: {
        review_id: "replace-with-review-id"
      },
      defaultBody: "{}"
    }
  ]
};
