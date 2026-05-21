import { apiRequest } from "../../lib/api";
import type { ApiResult } from "../../types";
import {
  TOOL_APPROVAL_STATUSES,
  type ToolApprovalDecision,
  type ToolApprovalRequest,
  type ToolApprovalStatus
} from "./types";

interface ToolApprovalCandidate {
  approval_id: string;
  status: string;
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

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isStringOrNull(value: unknown): value is string | null {
  return typeof value === "string" || value === null;
}

function isToolApprovalStatus(value: string): value is ToolApprovalStatus {
  return TOOL_APPROVAL_STATUSES.includes(value as ToolApprovalStatus);
}

function isToolApprovalCandidate(value: unknown): value is ToolApprovalCandidate {
  if (!isObject(value)) {
    return false;
  }
  return (
    typeof value.approval_id === "string" &&
    typeof value.status === "string" &&
    typeof value.reason === "string" &&
    typeof value.tool_name === "string" &&
    typeof value.operation === "string" &&
    typeof value.command === "string" &&
    typeof value.requested_by === "string" &&
    typeof value.tenant_id === "string" &&
    typeof value.details === "string" &&
    typeof value.created_at === "string" &&
    isStringOrNull(value.expires_at) &&
    typeof value.reviewed_by === "string" &&
    isStringOrNull(value.reviewed_at) &&
    typeof value.review_note === "string"
  );
}

export function asToolApprovalRequest(value: unknown): ToolApprovalRequest | null {
  if (!isToolApprovalCandidate(value)) {
    return null;
  }
  if (!isToolApprovalStatus(value.status)) {
    return null;
  }
  return {
    approval_id: value.approval_id,
    status: value.status,
    reason: value.reason,
    tool_name: value.tool_name,
    operation: value.operation,
    command: value.command,
    requested_by: value.requested_by,
    tenant_id: value.tenant_id,
    details: value.details,
    created_at: value.created_at,
    expires_at: value.expires_at,
    reviewed_by: value.reviewed_by,
    reviewed_at: value.reviewed_at,
    review_note: value.review_note
  };
}

export function asToolApprovalList(data: unknown): ToolApprovalRequest[] | null {
  if (!Array.isArray(data)) {
    return null;
  }
  const approvals = data.map((item) => asToolApprovalRequest(item));
  if (approvals.some((item) => item === null)) {
    return null;
  }
  return approvals as ToolApprovalRequest[];
}

export function fetchToolApprovals(
  status: ToolApprovalStatus | "all",
  token: string,
  apiKey: string
): Promise<ApiResult> {
  const query: Record<string, string> = { limit: "100" };
  if (status !== "all") {
    query.status = status;
  }
  return apiRequest({
    method: "GET",
    path: "/v1/approvals/tools",
    token,
    apiKey,
    query
  });
}

export function decideToolApproval(
  approvalId: string,
  decision: ToolApprovalDecision,
  reviewNote: string,
  token: string,
  apiKey: string
): Promise<ApiResult> {
  return apiRequest({
    method: "POST",
    path: "/v1/approvals/tools/{approval_id}/decision",
    pathParams: { approval_id: approvalId },
    token,
    apiKey,
    body: JSON.stringify({
      decision,
      review_note: reviewNote
    })
  });
}
