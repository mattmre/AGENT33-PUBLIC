export const TOOL_APPROVAL_STATUSES = [
  "pending",
  "approved",
  "rejected",
  "consumed",
  "expired"
] as const;

export type ToolApprovalStatus = (typeof TOOL_APPROVAL_STATUSES)[number];

export interface ToolApprovalRequest {
  approval_id: string;
  status: ToolApprovalStatus;
  reason: string;
  tool_name: string;
  operation: string;
  command: string;
  requested_by: string;
  tenant_id: string;
  details: string;
  created_at: string;
  expires_at: string | null;
  reviewed_by: string;
  reviewed_at: string | null;
  review_note: string;
}

export type ToolApprovalDecision = "approve" | "reject";
