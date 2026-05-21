import { describe, expect, it } from "vitest";

import { buildWorkflowDraftFromBrief } from "./builders";
import type { ProductBrief } from "./types";

describe("buildWorkflowDraftFromBrief", () => {
  it("converts a guided product brief into a Workflow Starter draft", () => {
    const brief: ProductBrief = {
      id: "brief-1",
      roleId: "founder",
      title: "Client portal MVP",
      idea: "Build a simple portal for client intake and project status.",
      audience: "Business owner and client",
      startingPoint: "Notes and form examples",
      desiredOutput: "Product brief and first build tasks",
      safetyScope: "Plan first and ask before code changes.",
      createdAt: "2026-04-28T00:00:00.000Z"
    };

    const draft = buildWorkflowDraftFromBrief(brief);

    expect(draft.id).toBe("guided-brief-1");
    expect(draft.name).toBe("client-portal-mvp");
    expect(draft.kind).toBe("automation-loop");
    expect(draft.goal).toContain("Role path: Founder");
    expect(draft.goal).toContain("Build a simple portal");
    expect(draft.sourceLabel).toBe("Guided intake: Client portal MVP");
    expect(draft.lifecyclePlan?.brief).toContain("Build a simple portal for client intake and project status.");
    expect(draft.lifecyclePlan?.handoff.join(" ")).toContain("Workflow Starter");
  });
});
