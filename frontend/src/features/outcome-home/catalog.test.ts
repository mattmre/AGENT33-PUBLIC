import { describe, expect, it } from "vitest";

import {
  OUTCOME_WORKFLOWS,
  buildCustomWorkflowDraft,
  buildWorkflowDraft,
  getFeaturedWorkflows
} from "./catalog";

describe("outcome workflow catalog", () => {
  it("ships a broad set of baked-in workflow cards", () => {
    expect(OUTCOME_WORKFLOWS.length).toBeGreaterThanOrEqual(12);
    expect(OUTCOME_WORKFLOWS.map((workflow) => workflow.id)).toContain("build-first-app");
    expect(OUTCOME_WORKFLOWS.map((workflow) => workflow.id)).toContain("enterprise-program");
  });

  it("maps workflow cards into Workflow Starter drafts", () => {
    const workflow = OUTCOME_WORKFLOWS.find((item) => item.id === "create-landing-page");
    expect(workflow).toBeDefined();
    if (workflow === undefined) {
      throw new Error("Expected create-landing-page workflow to exist");
    }

    const draft = buildWorkflowDraft(workflow);
    expect(draft.kind).toBe("automation-loop");
    expect(draft.name).toBe("create-landing-page");
    expect(draft.goal).toContain("landing page");
    expect(draft.sourceLabel).toBe("Create a landing page");
    expect(draft.lifecyclePlan?.brief[0]).toBe(workflow.goal);
    expect(draft.lifecyclePlan?.preview).toHaveLength(3);
  });

  it("creates custom drafts from plain-language goals", () => {
    const draft = buildCustomWorkflowDraft("Build a customer support dashboard");

    expect(draft.kind).toBe("automation-loop");
    expect(draft.goal).toBe("Build a customer support dashboard");
    expect(draft.output).toContain("safety gates");
    expect(draft.lifecyclePlan?.handoff.join(" ")).toContain("Open Operations");
  });

  it("keeps featured workflows focused", () => {
    expect(getFeaturedWorkflows()).toHaveLength(6);
  });
});
