import { describe, expect, it } from "vitest";

import { DEMO_SCENARIOS, findDemoScenario, getDefaultDemoScenario } from "./demoScenarios";

describe("demo scenarios", () => {
  it("ships no-setup sample outcomes with artifacts and workflow drafts", () => {
    expect(DEMO_SCENARIOS).toHaveLength(6);
    for (const scenario of DEMO_SCENARIOS) {
      expect(["Beginner", "Intermediate"]).toContain(scenario.complexity);
      expect(scenario.timeEstimate).toMatch(/preview$/);
      expect(scenario.prompt).not.toMatch(/orchestration|governance|autonomy/i);
      expect(scenario.sampleInputs.length).toBeGreaterThan(0);
      expect(scenario.runSteps.length).toBeGreaterThanOrEqual(4);
      expect(scenario.artifacts.length).toBeGreaterThanOrEqual(2);
      expect(scenario.starterDraft.sourceLabel).toContain("Demo Mode");
    }
  });

  it("falls back to the default scenario for unknown ids", () => {
    expect(findDemoScenario("missing")).toBe(getDefaultDemoScenario());
  });
});
