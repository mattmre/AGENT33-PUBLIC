import { describe, expect, it } from "vitest";

import type { ToolApprovalRequest } from "../features/safety-center/types";
import type { OperationsHubProcessSummary } from "../features/operations-hub/types";
import {
  buildCockpitOpsSafetySnapshot,
  getCockpitOpsSafetyRecordsByArtifactId,
  getCockpitOpsSafetyRecordsByKind
} from "./cockpitOpsSafety";

function createApproval(override: Partial<ToolApprovalRequest>): ToolApprovalRequest {
  return {
    approval_id: "approval-1",
    status: "pending",
    reason: "tool_call",
    tool_name: "shell",
    operation: "Run tests",
    command: "",
    requested_by: "builder",
    tenant_id: "local",
    details: "Run local validation",
    created_at: "2026-04-29T00:00:00.000Z",
    expires_at: "2026-04-29T02:00:00.000Z",
    reviewed_by: "",
    reviewed_at: null,
    review_note: "",
    ...override
  };
}

function createProcess(override: Partial<OperationsHubProcessSummary>): OperationsHubProcessSummary {
  return {
    id: "process-1",
    type: "workflow_run",
    status: "running",
    started_at: "2026-04-29T00:00:00.000Z",
    name: "Build feature",
    ...override
  };
}

describe("cockpit operations/safety adapter", () => {
  it("creates a permission-mode record linked to cockpit approval artifacts", () => {
    const snapshot = buildCockpitOpsSafetySnapshot({
      workspaceId: "solo-builder",
      permissionModeId: "ask"
    });

    expect(snapshot.permissionMode.id).toBe("ask");
    expect(snapshot.records).toEqual([
      expect.objectContaining({
        kind: "permission-mode",
        status: "needs-review",
        severity: "attention",
        relatedArtifactId: "solo-builder-approval",
        sourceLabel: "Permission mode control"
      })
    ]);
    expect(snapshot.activityEvents[0]).toMatchObject({
      type: "status",
      decisionState: "pending",
      relatedArtifactId: "solo-builder-approval"
    });
  });

  it("links clear and watched permission modes to non-approval artifacts", () => {
    const observeSnapshot = buildCockpitOpsSafetySnapshot({
      workspaceId: "solo-builder",
      permissionModeId: "observe"
    });
    const workspaceSnapshot = buildCockpitOpsSafetySnapshot({
      workspaceId: "solo-builder",
      permissionModeId: "workspace"
    });

    expect(observeSnapshot.records[0]).toMatchObject({
      status: "clear",
      relatedArtifactId: "solo-builder-outcome"
    });
    expect(workspaceSnapshot.records[0]).toMatchObject({
      status: "watching",
      relatedArtifactId: "solo-builder-activity"
    });
  });

  it("adapts pending tool approvals into approval and risk-linked cockpit records", () => {
    const snapshot = buildCockpitOpsSafetySnapshot({
      workspaceId: "test-review",
      permissionModeId: "workspace",
      now: Date.parse("2026-04-29T01:30:00.000Z"),
      approvals: [
        createApproval({
          approval_id: "safe-command",
          command: "npm test",
          operation: "Run tests"
        }),
        createApproval({
          approval_id: "delete-command",
          reason: "supervised_destructive",
          command: "Remove generated workspace",
          operation: "Delete workspace"
        }),
        createApproval({
          approval_id: "already-consumed",
          status: "consumed",
          operation: "Old approval"
        })
      ]
    });

    const approvals = getCockpitOpsSafetyRecordsByKind(snapshot.records, "tool-approval");

    expect(approvals).toHaveLength(2);
    expect(approvals[0]).toMatchObject({
      id: "test-review-ops-safety-approval-delete-command",
      status: "blocked",
      severity: "blocked",
      relatedArtifactId: "test-review-risk"
    });
    expect(approvals[1]).toMatchObject({
      id: "test-review-ops-safety-approval-safe-command",
      status: "needs-review",
      severity: "attention",
      relatedArtifactId: "test-review-approval"
    });
    expect(snapshot.activityEvents.filter((event) => event.type === "approval")).toEqual([
      expect.objectContaining({
        decisionState: "blocked",
        relatedArtifactId: "test-review-risk",
        createdAtLabel: "Requested 1.5 h ago",
        expiresAtLabel: "Expires in 30 min"
      }),
      expect.objectContaining({
        decisionState: "pending",
        relatedArtifactId: "test-review-approval",
        createdAtLabel: "Requested 1.5 h ago",
        expiresAtLabel: "Expires in 30 min"
      })
    ]);
  });

  it("bridges operations process status into activity, risk, and outcome artifacts", () => {
    const snapshot = buildCockpitOpsSafetySnapshot({
      workspaceId: "shipyard",
      permissionModeId: "observe",
      processes: [
        createProcess({
          id: "running-build",
          status: "running",
          name: "Build lane"
        }),
        createProcess({
          id: "failed-review",
          status: "failed",
          name: "Review lane"
        }),
        createProcess({
          id: "completed-handoff",
          status: "completed",
          name: "Handoff lane"
        })
      ]
    });

    expect(getCockpitOpsSafetyRecordsByArtifactId(snapshot.records, "shipyard-activity")).toEqual([
      expect.objectContaining({
        kind: "operation-process",
        status: "watching",
        title: "Build lane"
      })
    ]);
    expect(getCockpitOpsSafetyRecordsByArtifactId(snapshot.records, "shipyard-risk")).toEqual([
      expect.objectContaining({
        kind: "operation-process",
        status: "blocked",
        title: "Review lane"
      })
    ]);
    expect(
      getCockpitOpsSafetyRecordsByArtifactId(snapshot.records, "shipyard-outcome").filter(
        (record) => record.kind === "operation-process"
      )
    ).toEqual([
      expect.objectContaining({
        kind: "operation-process",
        status: "clear",
        title: "Handoff lane"
      })
    ]);
    expect(snapshot.summary).toMatchObject({
      blocked: 1,
      active: 1,
      primaryMessage: "1 cockpit safety item blocked."
    });
  });

  it("treats neutral process states as watched activity instead of risk", () => {
    const snapshot = buildCockpitOpsSafetySnapshot({
      workspaceId: "solo-builder",
      permissionModeId: "ask",
      processes: [
        createProcess({
          id: "queued-run",
          status: "queued",
          name: "Queued run"
        })
      ]
    });

    expect(getCockpitOpsSafetyRecordsByKind(snapshot.records, "operation-process")).toEqual([
      expect.objectContaining({
        status: "watching",
        severity: "info",
        relatedArtifactId: "solo-builder-activity",
        title: "Queued run"
      })
    ]);
  });

  it("keeps restricted mode blocked even without operations or approvals", () => {
    const snapshot = buildCockpitOpsSafetySnapshot({
      workspaceId: "research-build",
      permissionModeId: "restricted"
    });

    expect(snapshot.records).toEqual([
      expect.objectContaining({
        status: "blocked",
        relatedArtifactId: "research-build-risk",
        nextActionLabel: "Unlock a safer mode before running high-risk actions"
      })
    ]);
    expect(snapshot.summary).toMatchObject({
      totalRecords: 1,
      blocked: 1
    });
  });

  it("throws an actionable error for unknown workspaces", () => {
    expect(() => buildCockpitOpsSafetySnapshot({ workspaceId: "missing-workspace" })).toThrow(
      /Cannot build cockpit operations\/safety state for unknown workspaceId "missing-workspace"/
    );
  });
});
