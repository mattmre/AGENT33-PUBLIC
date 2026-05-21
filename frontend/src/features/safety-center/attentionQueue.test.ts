import { describe, expect, it } from "vitest";

import {
  buildAttentionQueue,
  buildBulkDecisionGuidance,
  getPolicyPreset,
  getRecommendedTokenPreset,
  getTimeGuidance
} from "./attentionQueue";
import type { ToolApprovalRequest } from "./types";

const approval: ToolApprovalRequest = {
  approval_id: "APR-1",
  status: "pending",
  reason: "supervised_destructive",
  tool_name: "filesystem",
  operation: "delete",
  command: "rm -rf temp",
  requested_by: "agent",
  tenant_id: "tenant",
  details: "cleanup",
  created_at: "2026-01-01T12:00:00Z",
  expires_at: "2026-01-01T12:10:00Z",
  reviewed_by: "",
  reviewed_at: null,
  review_note: ""
};

describe("attention queue helpers", () => {
  it("prioritizes destructive pending approvals", () => {
    const [item] = buildAttentionQueue([approval], Date.parse("2026-01-01T12:00:00Z"));

    expect(item.priority).toBe("high");
    expect(item.decisionMode).toBe("Individual approval only");
    expect(item.batchEligible).toBe(false);
    expect(item.tokenPreset).toBe("single_use");
    expect(item.recommendedAction).toContain("shortest-lived token");
  });

  it("builds time-bound decision guidance", () => {
    expect(getTimeGuidance(approval, Date.parse("2026-01-01T12:00:00Z"))).toContain("Expires in 10 min");
    expect(getTimeGuidance({ ...approval, expires_at: "" })).toBe("No expiry. Review when convenient.");
  });

  it("summarizes bulk decision safety", () => {
    const queue = buildAttentionQueue(
      [
        approval,
        {
          ...approval,
          approval_id: "APR-2",
          reason: "tool_policy_ask"
        }
      ],
      Date.parse("2026-01-01T12:00:00Z")
    );
    expect(buildBulkDecisionGuidance(queue)).toContain("1 high-risk item still needs individual review");
    expect(buildBulkDecisionGuidance(queue)).toContain("1 low/medium-risk item can use batch approval");
    expect(buildBulkDecisionGuidance([])).toBe("No pending attention items.");
  });

  it("uses command-specific policy presets for non-destructive commands", () => {
    const candidate = { ...approval, reason: "tool_policy_ask" } satisfies ToolApprovalRequest;

    expect(getPolicyPreset(candidate)).toContain("session_15m");
    expect(getRecommendedTokenPreset(candidate)).toBe("session_15m");
  });

  it("treats route mutations as high-risk token-gated work", () => {
    const routeApproval = {
      ...approval,
      approval_id: "APR-route",
      reason: "route_mutation",
      tool_name: "route:auth.api-keys",
      operation: "create_api_key",
      command: "POST auth.api-keys"
    } satisfies ToolApprovalRequest;

    const [item] = buildAttentionQueue([routeApproval], Date.parse("2026-01-01T12:00:00Z"));

    expect(item.priority).toBe("high");
    expect(item.reason).toBe("Sensitive route mutation");
    expect(getPolicyPreset(routeApproval)).toContain("X-Agent33-Approval-Token");
  });
});
