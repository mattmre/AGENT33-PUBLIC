import { describe, expect, it } from "vitest";

import { OUTCOME_WORKFLOWS } from "../outcome-home/catalog";
import {
  filterWorkflowCatalog,
  getDefaultWorkflowCatalogFilters,
  getWorkflowCatalogTags
} from "./filters";

describe("workflow catalog filters", () => {
  it("finds workflows by plain-language outcome text", () => {
    const workflows = filterWorkflowCatalog(OUTCOME_WORKFLOWS, {
      ...getDefaultWorkflowCatalogFilters(),
      query: "landing page, copy"
    });

    expect(workflows.map((workflow) => workflow.id)).toContain("create-landing-page");
  });

  it("filters by kind, safety level, and tag", () => {
    const workflows = filterWorkflowCatalog(OUTCOME_WORKFLOWS, {
      query: "",
      kind: "research",
      safetyLevel: "Plan-only",
      tag: "security"
    });

    expect(workflows).toHaveLength(1);
    expect(workflows[0]?.id).toBe("security-review");
  });

  it("returns sorted unique tags for the filter control", () => {
    const tags = getWorkflowCatalogTags(OUTCOME_WORKFLOWS);

    expect(tags).toContain("enterprise");
    expect(tags).toContain("starter");
    expect(tags).toEqual([...tags].sort((a, b) => a.localeCompare(b)));
  });
});
