import { apiRequest } from "../lib/api";
import {
  mergeWorkspaceSessions,
  type WorkspaceApiRecord,
  type WorkspaceSessionId,
  type WorkspaceSessionSummary
} from "./workspaces";
import {
  workspaceRecoverySummaryFromApi,
  type WorkspaceRecoveryApiRecord,
  type WorkspaceRecoverySummary
} from "./workspaceRecovery";

function asRecordArray(data: unknown): WorkspaceApiRecord[] {
  return Array.isArray(data) ? data.filter((item): item is WorkspaceApiRecord => typeof item === "object" && item !== null) : [];
}

function asRecoveryRecord(data: unknown): WorkspaceRecoveryApiRecord {
  return typeof data === "object" && data !== null ? (data as WorkspaceRecoveryApiRecord) : {};
}

export async function fetchWorkspaceSessions(
  token: string,
  apiKey: string
): Promise<ReadonlyArray<WorkspaceSessionSummary>> {
  const result = await apiRequest({
    method: "GET",
    path: "/v1/workspaces/",
    token,
    apiKey
  });
  if (!result.ok) {
    throw new Error(`Workspace API returned ${result.status}`);
  }
  return mergeWorkspaceSessions(asRecordArray(result.data));
}

export async function fetchWorkspaceRecoverySummary(
  workspaceId: WorkspaceSessionId,
  token: string,
  apiKey: string
): Promise<WorkspaceRecoverySummary> {
  const result = await apiRequest({
    method: "GET",
    path: "/v1/workspaces/{workspace_id}/recovery",
    pathParams: { workspace_id: workspaceId },
    token,
    apiKey
  });
  if (!result.ok) {
    throw new Error(`Workspace recovery API returned ${result.status}`);
  }
  return workspaceRecoverySummaryFromApi(workspaceId, asRecoveryRecord(result.data));
}
