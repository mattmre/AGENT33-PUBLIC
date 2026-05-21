import { describe, expect, it } from "vitest";

import { WORKSPACE_SESSION_IDS } from "./workspaces";
import { getWorkspaceRecoverySummary } from "./workspaceRecovery";

describe("workspace recovery summaries", () => {
  it("defines recovery controls for every workspace", () => {
    for (const workspaceId of WORKSPACE_SESSION_IDS) {
      const summary = getWorkspaceRecoverySummary(workspaceId);

      expect(summary.workspaceId).toBe(workspaceId);
      expect(summary.primaryMessage).toBeTruthy();
      expect(summary.snapshots.length).toBeGreaterThan(0);
      expect(summary.snapshots[0].resumeAction).toBeTruthy();
      expect(summary.snapshots[0].rollbackAction).toBeTruthy();
      expect(summary.snapshots[0].budgetLabel).toBeTruthy();
    }
  });
});
