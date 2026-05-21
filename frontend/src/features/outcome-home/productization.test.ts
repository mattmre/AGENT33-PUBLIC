import { describe, expect, it } from "vitest";

import { OUTCOME_WORKFLOWS } from "./catalog";
import {
  buildDryRunPreview,
  buildProductBuilderLifecycle,
  buildProductInputs,
  buildStarterPack,
  estimateWorkflowProduct,
  productizeWorkflow
} from "./productization";

describe("workflow productization", () => {
  const firstWorkflow = OUTCOME_WORKFLOWS[0];

  it("builds required launch inputs for a workflow", () => {
    const inputs = buildProductInputs(firstWorkflow);

    expect(inputs.length).toBeGreaterThanOrEqual(3);
    expect(inputs.some((input) => input.required)).toBe(true);
    expect(inputs[0].placeholder).toBeTruthy();
  });

  it("estimates duration, cost, risk, and review gate", () => {
    const estimate = estimateWorkflowProduct(firstWorkflow);

    expect(estimate.duration).toBe(firstWorkflow.estimatedTime);
    expect(estimate.cost).toContain("$");
    expect(["low", "medium", "high"]).toContain(estimate.risk);
    expect(estimate.reviewGate).toContain("Approve");
  });

  it("creates a dry-run preview without executing anything", () => {
    const steps = buildDryRunPreview(firstWorkflow);

    expect(steps).toHaveLength(3);
    expect(steps[0].title).toBe("Validate inputs");
    expect(steps[2].title).toBe("Ask for review");
  });

  it("creates a four-stage product-builder lifecycle", () => {
    const lifecycle = buildProductBuilderLifecycle(firstWorkflow);

    expect(lifecycle.brief[0]).toBe(firstWorkflow.goal);
    expect(lifecycle.plan.join(" ")).toContain(firstWorkflow.deliverables[0]);
    expect(lifecycle.preview).toHaveLength(3);
    expect(lifecycle.handoff.join(" ")).toContain(firstWorkflow.safetyLevel);
  });

  it("creates starter pack hints from workflow metadata", () => {
    const starterPack = buildStarterPack(firstWorkflow);

    expect(starterPack).toHaveLength(3);
    expect(starterPack[0].label).toContain(firstWorkflow.title);
  });

  it("productizes every catalog workflow", () => {
    for (const workflow of OUTCOME_WORKFLOWS) {
      const product = productizeWorkflow(workflow);
      expect(product.id).toBe(workflow.id);
      expect(product.inputs.length).toBeGreaterThan(0);
      expect(product.exampleOutputs.length).toBeGreaterThan(0);
      expect(product.dryRunSteps.length).toBe(3);
      expect(product.starterPack.length).toBe(3);
    }
  });
});
