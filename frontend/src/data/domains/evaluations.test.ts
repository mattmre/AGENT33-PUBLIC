import { describe, expect, it } from "vitest";

import { evaluationsDomain } from "./evaluations";

function getOperation(id: string) {
  const operation = evaluationsDomain.operations.find((entry) => entry.id === id);
  expect(operation).toBeDefined();
  return operation!;
}

describe("evaluationsDomain", () => {
  it("keeps submit-results defaults aligned with the backend gate contract", () => {
    const body = JSON.parse(getOperation("eval-run-results").defaultBody ?? "{}");
    const itemIds = body.task_results.map((entry: { item_id: string }) => entry.item_id);

    expect(itemIds).toEqual(["GT-01", "GT-04", "GC-01"]);
    for (const result of body.task_results) {
      expect(result).toHaveProperty("checks_passed");
      expect(result).toHaveProperty("checks_total");
      expect(result).toHaveProperty("diff_lines");
      expect(result).toHaveProperty("duration_ms");
    }
    expect(body.task_results[2]).toMatchObject({
      failure_category: "",
      flaky: false
    });
  });

  it("uses backend request fields for regression triage and resolution", () => {
    const triageBody = JSON.parse(getOperation("eval-triage").defaultBody ?? "{}");
    expect(triageBody).toEqual({
      status: "investigating",
      assignee: "qa-team"
    });

    const resolveBody = JSON.parse(getOperation("eval-resolve").defaultBody ?? "{}");
    expect(resolveBody).toEqual({
      resolved_by: "qa-team",
      fix_commit: "abcdef"
    });
  });
});
