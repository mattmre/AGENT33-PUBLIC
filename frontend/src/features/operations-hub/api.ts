import { apiRequest } from "../../lib/api";
import type { ApiResult } from "../../types";
import type {
  IngestionAssetHistoryEntry,
  IngestionAssetHistoryResponse,
  IngestionAssetSummary,
  OperationsHubControlAction,
  OperationsHubProcessAction,
  OperationsHubProcessDetail,
  OperationsHubProcessSummary,
  OperationsHubResponse,
  RecoveryReplaySummary,
  RecoverySessionSummary
} from "./types";

interface ProcessSummaryCandidate {
  id: string;
  type: string;
  status: string;
  started_at: string;
  name: string;
  metadata?: unknown;
}

interface IngestionAssetCandidate {
  id: string;
  name: string;
  asset_type: string;
  status: string;
  confidence: string;
  source_uri: string | null;
  tenant_id: string;
  created_at: string;
  updated_at: string;
  validated_at: string | null;
  published_at: string | null;
  revoked_at: string | null;
  revocation_reason: string | null;
  metadata: unknown;
}

interface IngestionAssetHistoryEntryCandidate {
  asset_id: string;
  tenant_id: string;
  from_status: string;
  to_status: string;
  event_type: string;
  operator: string;
  reason: string;
  details: unknown;
  occurred_at: string;
}

interface RecoverySessionSummaryCandidate {
  session_id: string;
  purpose: string;
  status: string;
  started_at: string;
  updated_at: string;
  ended_at: string | null;
  task_count: number;
  tasks_completed: number;
  event_count: number;
  parent_session_id: string | null;
  tenant_id: string;
}

interface RecoveryReplaySummaryCandidate {
  total_events: number;
  by_type: Record<string, unknown>;
  duration_seconds: number;
  first_event_at: string;
  last_event_at: string;
}

interface CheckpointResponseCandidate {
  status: string;
  session_id: string;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isStringOrNull(value: unknown): value is string | null {
  return typeof value === "string" || value === null;
}

function isProcessSummary(value: unknown): value is ProcessSummaryCandidate {
  if (!isObject(value)) {
    return false;
  }
  return (
    typeof value.id === "string" &&
    typeof value.type === "string" &&
    typeof value.status === "string" &&
    typeof value.started_at === "string" &&
    typeof value.name === "string"
  );
}

function isIngestionAsset(value: unknown): value is IngestionAssetCandidate {
  if (!isObject(value)) {
    return false;
  }
  return (
    typeof value.id === "string" &&
    typeof value.name === "string" &&
    typeof value.asset_type === "string" &&
    typeof value.status === "string" &&
    typeof value.confidence === "string" &&
    isStringOrNull(value.source_uri) &&
    typeof value.tenant_id === "string" &&
    typeof value.created_at === "string" &&
    typeof value.updated_at === "string" &&
    isStringOrNull(value.validated_at) &&
    isStringOrNull(value.published_at) &&
    isStringOrNull(value.revoked_at) &&
    isStringOrNull(value.revocation_reason) &&
    isObject(value.metadata)
  );
}

function isRecoverySessionSummary(value: unknown): value is RecoverySessionSummaryCandidate {
  if (!isObject(value)) {
    return false;
  }
  return (
    typeof value.session_id === "string" &&
    typeof value.purpose === "string" &&
    typeof value.status === "string" &&
    typeof value.started_at === "string" &&
    typeof value.updated_at === "string" &&
    isStringOrNull(value.ended_at) &&
    typeof value.task_count === "number" &&
    typeof value.tasks_completed === "number" &&
    typeof value.event_count === "number" &&
    isStringOrNull(value.parent_session_id) &&
    typeof value.tenant_id === "string"
  );
}

function isRecoveryReplaySummary(value: unknown): value is RecoveryReplaySummaryCandidate {
  if (!isObject(value) || !isObject(value.by_type)) {
    return false;
  }
  return (
    typeof value.total_events === "number" &&
    typeof value.duration_seconds === "number" &&
    typeof value.first_event_at === "string" &&
    typeof value.last_event_at === "string"
  );
}

function isCheckpointResponse(value: unknown): value is CheckpointResponseCandidate {
  return isObject(value) && typeof value.status === "string" && typeof value.session_id === "string";
}

function toProcessSummary(value: unknown): OperationsHubProcessSummary | null {
  if (!isProcessSummary(value)) {
    return null;
  }
  const metadata =
    value.metadata !== undefined && isObject(value.metadata)
      ? value.metadata
      : undefined;
  return {
    id: value.id,
    type: value.type,
    status: value.status,
    started_at: value.started_at,
    name: value.name,
    metadata
  };
}

function toIngestionAsset(value: unknown): IngestionAssetSummary | null {
  if (!isIngestionAsset(value)) {
    return null;
  }
  const metadata = value.metadata as Record<string, unknown>;
  return {
    id: value.id,
    name: value.name,
    asset_type: value.asset_type,
    status: value.status,
    confidence: value.confidence,
    source_uri: value.source_uri,
    tenant_id: value.tenant_id,
    created_at: value.created_at,
    updated_at: value.updated_at,
    validated_at: value.validated_at,
    published_at: value.published_at,
    revoked_at: value.revoked_at,
    revocation_reason: value.revocation_reason,
    metadata
  };
}

function toRecoverySessionSummary(value: unknown): RecoverySessionSummary | null {
  if (!isRecoverySessionSummary(value)) {
    return null;
  }
  return {
    session_id: value.session_id,
    purpose: value.purpose,
    status: value.status,
    started_at: value.started_at,
    updated_at: value.updated_at,
    ended_at: value.ended_at,
    task_count: value.task_count,
    tasks_completed: value.tasks_completed,
    event_count: value.event_count,
    parent_session_id: value.parent_session_id,
    tenant_id: value.tenant_id
  };
}

function toRecoveryReplaySummary(value: unknown): RecoveryReplaySummary | null {
  if (!isRecoveryReplaySummary(value)) {
    return null;
  }
  const byType = Object.entries(value.by_type).every(
    ([key, count]) => typeof key === "string" && typeof count === "number"
  )
    ? (value.by_type as Record<string, number>)
    : null;
  if (byType === null) {
    return null;
  }
  return {
    total_events: value.total_events,
    by_type: byType,
    duration_seconds: value.duration_seconds,
    first_event_at: value.first_event_at,
    last_event_at: value.last_event_at
  };
}

function toHistoryEntry(value: unknown): IngestionAssetHistoryEntry | null {
  if (!isObject(value)) {
    return null;
  }
  const candidate = value as Partial<IngestionAssetHistoryEntryCandidate>;
  if (
    typeof candidate.asset_id !== "string" ||
    typeof candidate.tenant_id !== "string" ||
    typeof candidate.from_status !== "string" ||
    typeof candidate.to_status !== "string" ||
    typeof candidate.event_type !== "string" ||
    typeof candidate.operator !== "string" ||
    typeof candidate.reason !== "string" ||
    !isObject(candidate.details) ||
    typeof candidate.occurred_at !== "string"
  ) {
    return null;
  }
  return {
    asset_id: candidate.asset_id,
    tenant_id: candidate.tenant_id,
    from_status: candidate.from_status,
    to_status: candidate.to_status,
    event_type: candidate.event_type,
    operator: candidate.operator,
    reason: candidate.reason,
    details: candidate.details,
    occurred_at: candidate.occurred_at
  };
}

function toProcessActions(value: unknown): OperationsHubProcessAction[] | undefined {
  if (!Array.isArray(value)) {
    return undefined;
  }
  const actions = value
    .map((item) => {
      if (!isObject(item)) {
        return null;
      }
      if (
        typeof item.step_id !== "string" ||
        typeof item.action_count !== "number" ||
        (item.completed_at !== null && typeof item.completed_at !== "string")
      ) {
        return null;
      }
      return {
        step_id: item.step_id,
        action_count: item.action_count,
        completed_at: item.completed_at
      };
    })
    .filter((item): item is OperationsHubProcessAction => item !== null);
  return actions;
}

export function asOperationsHubResponse(data: unknown): OperationsHubResponse | null {
  if (!isObject(data)) {
    return null;
  }
  if (
    typeof data.timestamp !== "string" ||
    typeof data.active_count !== "number" ||
    !Array.isArray(data.processes)
  ) {
    return null;
  }
  const processes = data.processes
    .map((item) => toProcessSummary(item))
    .filter((item): item is OperationsHubProcessSummary => item !== null);
  if (processes.length !== data.processes.length) {
    return null;
  }
  return {
    timestamp: data.timestamp,
    active_count: data.active_count,
    processes
  };
}

export function asOperationsHubDetail(data: unknown): OperationsHubProcessDetail | null {
  const summary = toProcessSummary(data);
  if (summary === null || !isObject(data)) {
    return null;
  }
  const actions = data.actions !== undefined ? toProcessActions(data.actions) : undefined;
  if (data.actions !== undefined && actions === undefined) {
    return null;
  }
  return {
    ...summary,
    actions
  };
}

export function asIngestionAssetHistoryResponse(data: unknown): IngestionAssetHistoryResponse | null {
  if (!isObject(data) || !Array.isArray(data.history)) {
    return null;
  }
  const asset = toIngestionAsset(data.asset);
  if (asset === null) {
    return null;
  }
  const history = data.history
    .map((item) => toHistoryEntry(item))
    .filter((item): item is IngestionAssetHistoryEntry => item !== null);
  if (history.length !== data.history.length) {
    return null;
  }
  return {
    asset,
    history
  };
}

export function asIngestionAssetList(data: unknown): IngestionAssetSummary[] | null {
  if (!Array.isArray(data)) {
    return null;
  }
  const assets = data
    .map((item) => toIngestionAsset(item))
    .filter((item): item is IngestionAssetSummary => item !== null);
  return assets.length === data.length ? assets : null;
}

export function asRecoverySessionSummary(data: unknown): RecoverySessionSummary | null {
  return toRecoverySessionSummary(data);
}

export function asRecoverySessionSummaries(data: unknown): RecoverySessionSummary[] | null {
  if (!Array.isArray(data)) {
    return null;
  }
  const sessions = data
    .map((item) => toRecoverySessionSummary(item))
    .filter((item): item is RecoverySessionSummary => item !== null);
  return sessions.length === data.length ? sessions : null;
}

export function asRecoveryReplaySummary(data: unknown): RecoveryReplaySummary | null {
  return toRecoveryReplaySummary(data);
}

export function isRecoveryCheckpointResponse(data: unknown): data is CheckpointResponseCandidate {
  return isCheckpointResponse(data);
}

export async function fetchOperationsHub(token: string, apiKey: string): Promise<ApiResult> {
  return apiRequest({
    method: "GET",
    path: "/v1/operations/hub",
    token,
    apiKey
  });
}

export async function fetchProcessDetail(
  processId: string,
  token: string,
  apiKey: string
): Promise<ApiResult> {
  return apiRequest({
    method: "GET",
    path: "/v1/operations/processes/{process_id}",
    pathParams: { process_id: processId },
    token,
    apiKey
  });
}

export async function controlProcess(
  processId: string,
  action: OperationsHubControlAction,
  token: string,
  apiKey: string
): Promise<ApiResult> {
  return apiRequest({
    method: "POST",
    path: "/v1/operations/processes/{process_id}/control",
    pathParams: { process_id: processId },
    body: JSON.stringify({ action }),
    token,
    apiKey
  });
}

export async function fetchReviewQueue(token: string, apiKey: string): Promise<ApiResult> {
  return apiRequest({
    method: "GET",
    path: "/v1/ingestion/review-queue",
    token,
    apiKey
  });
}

export async function fetchIncompleteSessions(token: string, apiKey: string): Promise<ApiResult> {
  return apiRequest({
    method: "GET",
    path: "/v1/sessions/incomplete",
    token,
    apiKey
  });
}

export async function fetchReplaySummary(
  sessionId: string,
  token: string,
  apiKey: string
): Promise<ApiResult> {
  return apiRequest({
    method: "GET",
    path: "/v1/sessions/{session_id}/replay/summary",
    pathParams: { session_id: sessionId },
    token,
    apiKey
  });
}

export async function resumeIncompleteSession(
  sessionId: string,
  token: string,
  apiKey: string
): Promise<ApiResult> {
  return apiRequest({
    method: "POST",
    path: "/v1/sessions/{session_id}/resume",
    pathParams: { session_id: sessionId },
    token,
    apiKey
  });
}

export async function checkpointSession(
  sessionId: string,
  token: string,
  apiKey: string
): Promise<ApiResult> {
  return apiRequest({
    method: "POST",
    path: "/v1/sessions/{session_id}/checkpoint",
    pathParams: { session_id: sessionId },
    token,
    apiKey
  });
}

export async function fetchAssetHistory(
  assetId: string,
  token: string,
  apiKey: string
): Promise<ApiResult> {
  return apiRequest({
    method: "GET",
    path: "/v1/ingestion/candidates/{asset_id}/history",
    pathParams: { asset_id: assetId },
    token,
    apiKey
  });
}

export async function approveReviewAsset(
  assetId: string,
  operator: string,
  reason: string,
  token: string,
  apiKey: string
): Promise<ApiResult> {
  return apiRequest({
    method: "POST",
    path: "/v1/ingestion/review-queue/{asset_id}/approve",
    pathParams: { asset_id: assetId },
    body: JSON.stringify({ operator, reason }),
    token,
    apiKey
  });
}

export async function rejectReviewAsset(
  assetId: string,
  operator: string,
  reason: string,
  token: string,
  apiKey: string
): Promise<ApiResult> {
  return apiRequest({
    method: "POST",
    path: "/v1/ingestion/review-queue/{asset_id}/reject",
    pathParams: { asset_id: assetId },
    body: JSON.stringify({ operator, reason }),
    token,
    apiKey
  });
}
