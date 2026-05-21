import type { ToolApprovalRequest } from "./types";

export type AttentionPriority = "high" | "medium" | "low";
export type ApprovalTokenPresetId = "single_use" | "session_15m" | "session_1h" | "workday";

export interface AttentionQueueItem {
  id: string;
  title: string;
  priority: AttentionPriority;
  reason: string;
  decisionMode: string;
  batchEligible: boolean;
  tokenPreset: ApprovalTokenPresetId;
  timeGuidance: string;
  recommendedAction: string;
}

function getTitle(approval: ToolApprovalRequest): string {
  return approval.operation ? `${approval.tool_name}: ${approval.operation}` : approval.tool_name;
}

function isHighRiskApproval(approval: ToolApprovalRequest): boolean {
  return approval.reason === "supervised_destructive" || approval.reason === "route_mutation";
}

export function isBatchEligibleApproval(approval: ToolApprovalRequest): boolean {
  return approval.status === "pending" && !isHighRiskApproval(approval);
}

function getPriority(approval: ToolApprovalRequest): AttentionPriority {
  if (isHighRiskApproval(approval)) {
    return "high";
  }
  if (approval.command || approval.operation) {
    return "medium";
  }
  return "low";
}

export function getRecommendedTokenPreset(approval: ToolApprovalRequest): ApprovalTokenPresetId {
  if (isHighRiskApproval(approval)) {
    return "single_use";
  }
  if (approval.command || approval.operation) {
    return "session_15m";
  }
  return "session_1h";
}

export function getPolicyPreset(approval: ToolApprovalRequest): string {
  const preset = getRecommendedTokenPreset(approval);
  if (approval.reason === "supervised_destructive") {
    return `Approve individually only after verifying the exact command and target. If work should continue, prefer a ${preset} approval token.`;
  }
  if (approval.reason === "route_mutation") {
    return `Sensitive route mutation. Approve individually, then retry the route with a ${preset} token in X-Agent33-Approval-Token.`;
  }
  if (approval.command) {
    return `Batch-approve only when requester, workflow, and command intent match. Prefer ${preset} over longer-lived access.`;
  }
  return `Low-risk approvals can be grouped. Prefer ${preset} instead of longer-lived approval tokens.`;
}

export function getTimeGuidance(approval: ToolApprovalRequest, now = Date.now()): string {
  if (!approval.expires_at) {
    return "No expiry. Review when convenient.";
  }
  const expiresAt = Date.parse(approval.expires_at);
  if (!Number.isFinite(expiresAt)) {
    return "Expiry unknown. Review manually.";
  }
  const minutes = Math.round((expiresAt - now) / 60_000);
  if (minutes <= 0) {
    return "Expired or expiring now. Reject unless you can re-run safely.";
  }
  if (minutes <= 30) {
    return `Expires in ${minutes} min. Decide soon or reject.`;
  }
  return `Expires in ${minutes} min. Safe to review in order.`;
}

export function buildAttentionQueue(
  approvals: ToolApprovalRequest[],
  now = Date.now()
): AttentionQueueItem[] {
  return approvals
    .filter((approval) => approval.status === "pending")
    .map((approval) => {
      const priority = getPriority(approval);
      const batchEligible = isBatchEligibleApproval(approval);
      return {
        id: approval.approval_id,
        title: getTitle(approval),
        priority,
        reason:
          priority === "high"
            ? approval.reason === "route_mutation"
              ? "Sensitive route mutation"
              : "Destructive or high-impact tool call"
            : priority === "medium"
              ? "Tool call needs operator review"
              : "Routine approval",
        decisionMode: batchEligible ? "Batch eligible" : "Individual approval only",
        batchEligible,
        tokenPreset: getRecommendedTokenPreset(approval),
        timeGuidance: getTimeGuidance(approval, now),
        recommendedAction:
          priority === "high"
            ? "Review one by one and use the shortest-lived token that still fits the task."
            : batchEligible
              ? "Batch-approve only matching low/medium-risk items with a review note."
              : "Approve with a review note if expected."
      };
    })
    .sort((a, b) => {
      const priorityOrder: Record<AttentionPriority, number> = { high: 0, medium: 1, low: 2 };
      return priorityOrder[a.priority] - priorityOrder[b.priority];
    });
}

export function buildBulkDecisionGuidance(items: AttentionQueueItem[]): string {
  if (items.length === 0) {
    return "No pending attention items.";
  }
  const highPriority = items.filter((item) => item.priority === "high").length;
  const batchEligible = items.filter((item) => item.batchEligible).length;
  if (highPriority > 0 && batchEligible > 0) {
    return `${highPriority} high-risk item${highPriority === 1 ? " still needs" : "s still need"} individual review. ${batchEligible} low/medium-risk item${batchEligible === 1 ? "" : "s"} can use batch approval with a short-lived token preset if follow-through is required.`;
  }
  if (highPriority > 0) {
    return `${highPriority} high-risk item${highPriority === 1 ? " requires" : "s require"} individual approval and usually a single_use token.`;
  }
  return `${batchEligible} low/medium-risk item${batchEligible === 1 ? "" : "s"} can use batch approval. Prefer short-lived presets such as session_15m or session_1h.`;
}
