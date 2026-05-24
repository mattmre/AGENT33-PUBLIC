import { describe, expect, it } from "vitest";

import { reviewsDomain } from "./reviews";

function getOperation(id: string) {
  const operation = reviewsDomain.operations.find((entry) => entry.id === id);
  expect(operation).toBeDefined();
  return operation!;
}

describe("reviewsDomain", () => {
  it("exposes the structured approval-rationale operation", () => {
    const operation = getOperation("reviews-approve-with-rationale");

    expect(operation.method).toBe("POST");
    expect(operation.path).toBe("/v1/reviews/{review_id}/approve-with-rationale");
    expect(operation.defaultPathParams).toEqual({
      review_id: "replace-with-review-id"
    });
  });

  it("keeps approval-rationale defaults aligned with the backend contract", () => {
    const body = JSON.parse(
      getOperation("reviews-approve-with-rationale").defaultBody ?? "{}"
    );

    expect(body).toEqual({
      decision: "approved",
      rationale: "All checks pass.",
      modification_summary: "",
      conditions: [],
      linked_intake_id: null
    });
  });
});
