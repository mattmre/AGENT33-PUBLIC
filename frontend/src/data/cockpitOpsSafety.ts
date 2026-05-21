import type { ToolApprovalRequest } from "../features/safety-center/types";
import { buildAttentionQueue, getPolicyPreset } from "../features/safety-center/attentionQueue";
import type { OperationsHubProcessSummary, OperationsTimelineTone } from "../features/operations-hub/types";
import { getStatusLabel, getTimelineTone, summarizeOperations } from "../features/operations-hub/helpers";
import type { CockpitActivityEvent, CockpitActivitySeverity } from "./cockpitActivity";
import { createCockpitActivityEvent } from "./cockpitActivity";
import type { CockpitArtifact, CockpitArtifactKind } from "./cockpitArtifacts";
import { getCockpitArtifactsForWorkspace } from "./cockpitArtifacts";
import type { PermissionModeDefinition, PermissionModeId } from "./permissionModes";
import { DEFAULT_PERMISSION_MODE_ID, getPermissionMode } from "./permissionModes";
import type { WorkspaceSessionId } from "./workspaces";
import { WORKSPACE_SESSION_IDS, isWorkspaceSessionId } from "./workspaces";

export const COCKPIT_OPS_SAFETY_RECORD_KINDS = ["permission-mode", "tool-approval", "operation-process"] as const;
export const COCKPIT_OPS_SAFETY_RECORD_STATUSES = ["clear", "watching", "needs-review", "blocked"] as const;

export type CockpitOpsSafetyRecordKind = (typeof COCKPIT_OPS_SAFETY_RECORD_KINDS)[number];
export type CockpitOpsSafetyRecordStatus = (typeof COCKPIT_OPS_SAFETY_RECORD_STATUSES)[number];

export interface CockpitOpsSafetyInput {
  readonly workspaceId: string;
  readonly permissionModeId?: PermissionModeId;
  readonly approvals?: ReadonlyArray<ToolApprovalRequest>;
  readonly processes?: ReadonlyArray<OperationsHubProcessSummary>;
  readonly now?: number;
}

export interface CockpitOpsSafetyRecord {
  readonly id: string;
  readonly workspaceId: WorkspaceSessionId;
  readonly kind: CockpitOpsSafetyRecordKind;
  readonly status: CockpitOpsSafetyRecordStatus;
  readonly severity: CockpitActivitySeverity;
  readonly title: string;
  readonly summary: string;
  readonly sourceLabel: string;
  readonly relatedArtifactId: string;
  readonly relatedArtifactKind: CockpitArtifactKind;
  readonly relatedActivityEventId: string;
  readonly createdAtLabel?: string;
  readonly expiresAtLabel?: string;
  readonly nextActionLabel: string;
}

export interface CockpitOpsSafetySnapshot {
  readonly workspaceId: WorkspaceSessionId;
  readonly permissionMode: PermissionModeDefinition;
  readonly summary: {
    readonly totalRecords: number;
    readonly blocked: number;
    readonly needsReview: number;
    readonly active: number;
    readonly primaryMessage: string;
    readonly nextAction: string;
  };
  readonly records: ReadonlyArray<CockpitOpsSafetyRecord>;
  readonly activityEvents: ReadonlyArray<CockpitActivityEvent>;
  readonly artifacts: ReadonlyArray<CockpitArtifact>;
}

interface OpsSafetyBuildContext {
  readonly workspaceId: WorkspaceSessionId;
  readonly permissionMode: PermissionModeDefinition;
  readonly artifactsByKind: Readonly<Record<CockpitArtifactKind, CockpitArtifact>>;
  readonly approvals: ReadonlyArray<ToolApprovalRequest>;
  readonly processes: ReadonlyArray<OperationsHubProcessSummary>;
  readonly now: number;
}

function assertWorkspaceId(workspaceId: string): asserts workspaceId is WorkspaceSessionId {
  if (!isWorkspaceSessionId(workspaceId)) {
    throw new Error(
      `Cannot build cockpit operations/safety state for unknown workspaceId "${workspaceId}". Known workspace IDs: ${WORKSPACE_SESSION_IDS.join(", ")}.`
    );
  }
}

function getPermissionStatus(mode: PermissionModeDefinition): CockpitOpsSafetyRecordStatus {
  if (mode.id === "restricted") {
    return "blocked";
  }
  if (mode.id === "observe") {
    return "clear";
  }
  if (mode.id === "workspace") {
    return "watching";
  }
  return "needs-review";
}

function getPermissionArtifactKind(status: CockpitOpsSafetyRecordStatus): CockpitArtifactKind {
  if (status === "blocked") {
    return "risk";
  }
  if (status === "clear") {
    return "outcome";
  }
  if (status === "watching") {
    return "activity";
  }
  return "approval";
}

function getSeverity(status: CockpitOpsSafetyRecordStatus): CockpitActivitySeverity {
  switch (status) {
    case "blocked":
      return "blocked";
    case "needs-review":
      return "attention";
    case "clear":
      return "success";
    case "watching":
      return "info";
    default: {
      const unexpectedStatus: never = status;
      throw new Error(`Unhandled cockpit ops/safety status: ${unexpectedStatus}`);
    }
  }
}

function createRecord(
  context: OpsSafetyBuildContext,
  record: Omit<CockpitOpsSafetyRecord, "workspaceId" | "severity" | "relatedArtifactId">
): CockpitOpsSafetyRecord {
  return {
    workspaceId: context.workspaceId,
    severity: getSeverity(record.status),
    relatedArtifactId: context.artifactsByKind[record.relatedArtifactKind].id,
    ...record
  };
}

function createPermissionRecord(context: OpsSafetyBuildContext): CockpitOpsSafetyRecord {
  const status = getPermissionStatus(context.permissionMode);

  return createRecord(context, {
    id: `${context.workspaceId}-ops-safety-permission-${context.permissionMode.id}`,
    kind: "permission-mode",
    status,
    title: context.permissionMode.label,
    summary: `${context.permissionMode.allowedNow}. ${context.permissionMode.reviewGate}.`,
    sourceLabel: "Permission mode control",
    relatedArtifactKind: getPermissionArtifactKind(status),
    relatedActivityEventId: `${context.workspaceId}-ops-safety-event-permission-${context.permissionMode.id}`,
    nextActionLabel:
      status === "blocked" ? "Unlock a safer mode before running high-risk actions" : context.permissionMode.reviewGate
  });
}

function getApprovalArtifactKind(priority: "high" | "medium" | "low"): CockpitArtifactKind {
  return priority === "high" ? "risk" : "approval";
}

function formatRelativeHours(minutes: number): string {
  const hours = minutes / 60;
  return `${Number.isInteger(hours) ? hours : hours.toFixed(1)} h`;
}

function formatApprovalCreatedAtLabel(createdAt: string, now: number): string {
  const timestamp = Date.parse(createdAt);
  if (!Number.isFinite(timestamp)) {
    return "Request time unknown";
  }

  const minutes = Math.max(0, Math.round((now - timestamp) / 60_000));
  if (minutes === 0) {
    return "Requested just now";
  }
  if (minutes < 60) {
    return `Requested ${minutes} min ago`;
  }
  return `Requested ${formatRelativeHours(minutes)} ago`;
}

function formatApprovalExpiresAtLabel(expiresAt: string | null, now: number): string {
  if (!expiresAt) {
    return "No expiry recorded";
  }

  const timestamp = Date.parse(expiresAt);
  if (!Number.isFinite(timestamp)) {
    return "Expiry unknown";
  }

  const minutes = Math.max(0, Math.ceil((timestamp - now) / 60_000));
  if (minutes <= 0) {
    return "Expired or expiring now";
  }
  if (minutes < 60) {
    return `Expires in ${minutes} min`;
  }
  return `Expires in ${formatRelativeHours(minutes)}`;
}

function createApprovalRecords(context: OpsSafetyBuildContext): ReadonlyArray<CockpitOpsSafetyRecord> {
  const approvalsById = new Map(context.approvals.map((approval) => [approval.approval_id, approval]));

  return buildAttentionQueue([...context.approvals], context.now).map((item) => {
    const approval = approvalsById.get(item.id);

    return createRecord(context, {
      id: `${context.workspaceId}-ops-safety-approval-${item.id}`,
      kind: "tool-approval",
      status: item.priority === "high" ? "blocked" : "needs-review",
      title: item.title,
      summary: `${item.reason}. ${item.timeGuidance} ${approval ? getPolicyPreset(approval) : ""}`,
      sourceLabel: "Safety attention queue",
      relatedArtifactKind: getApprovalArtifactKind(item.priority),
      relatedActivityEventId: `${context.workspaceId}-ops-safety-event-approval-${item.id}`,
      createdAtLabel: approval ? formatApprovalCreatedAtLabel(approval.created_at, context.now) : undefined,
      expiresAtLabel: approval ? formatApprovalExpiresAtLabel(approval.expires_at, context.now) : undefined,
      nextActionLabel: item.recommendedAction
    });
  });
}

function getProcessStatus(tone: OperationsTimelineTone, status: string): CockpitOpsSafetyRecordStatus {
  if (tone === "active") {
    return "watching";
  }
  if (tone === "done") {
    return "clear";
  }
  if (tone === "attention") {
    const normalized = status.trim().toLowerCase();
    return normalized === "failed" || normalized === "error" || normalized === "rejected" ? "blocked" : "needs-review";
  }
  return "watching";
}

function getProcessArtifactKind(status: CockpitOpsSafetyRecordStatus): CockpitArtifactKind {
  if (status === "blocked" || status === "needs-review") {
    return "risk";
  }
  if (status === "clear") {
    return "outcome";
  }
  return "activity";
}

function createProcessRecords(context: OpsSafetyBuildContext): ReadonlyArray<CockpitOpsSafetyRecord> {
  return context.processes.map((process) => {
    const tone = getTimelineTone(process.status);
    const status = getProcessStatus(tone, process.status);
    const statusLabel = getStatusLabel(process.status);

    return createRecord(context, {
      id: `${context.workspaceId}-ops-safety-process-${process.id}`,
      kind: "operation-process",
      status,
      title: process.name,
      summary: `${process.type.replace(/[_-]+/g, " ")} is ${statusLabel.toLowerCase()}.`,
      sourceLabel: "Operations Hub",
      relatedArtifactKind: getProcessArtifactKind(status),
      relatedActivityEventId: `${context.workspaceId}-ops-safety-event-process-${process.id}`,
      nextActionLabel:
        status === "blocked"
          ? "Open Operations Hub and fix or cancel the process"
          : status === "needs-review"
            ? "Review process state before continuing"
            : status === "clear"
              ? "Review completed output"
              : "Watch the process timeline"
    });
  });
}

function createActivityEvent(record: CockpitOpsSafetyRecord): CockpitActivityEvent {
  return createCockpitActivityEvent({
    id: record.relatedActivityEventId,
    workspaceId: record.workspaceId,
    type:
      record.kind === "tool-approval"
        ? "approval"
        : record.status === "blocked"
          ? "blocker"
          : record.status === "clear"
            ? "validation"
            : "status",
    severity: record.severity,
    senderRole: record.kind === "permission-mode" ? "Operator" : "Coordinator",
    recipientRole: record.status === "clear" ? "Operator" : "All",
    title: record.title,
    summary: record.summary,
    timestampLabel: record.sourceLabel,
    createdAtLabel: record.createdAtLabel,
    expiresAtLabel: record.expiresAtLabel,
    decisionState:
      record.status === "blocked"
        ? "blocked"
        : record.status === "needs-review"
          ? "pending"
          : record.status === "clear"
            ? "not-required"
            : "not-required",
    relatedArtifactId: record.relatedArtifactId,
    nextActionLabel: record.nextActionLabel
  });
}

function getArtifactsByKind(artifacts: ReadonlyArray<CockpitArtifact>): Readonly<Record<CockpitArtifactKind, CockpitArtifact>> {
  return Object.fromEntries(artifacts.map((artifact) => [artifact.kind, artifact])) as Record<
    CockpitArtifactKind,
    CockpitArtifact
  >;
}

function summarizeOpsSafety(
  records: ReadonlyArray<CockpitOpsSafetyRecord>,
  processes: ReadonlyArray<OperationsHubProcessSummary>
): CockpitOpsSafetySnapshot["summary"] {
  const counts = records.reduce(
    (current, record) => ({
      blocked: current.blocked + (record.status === "blocked" ? 1 : 0),
      needsReview: current.needsReview + (record.status === "needs-review" ? 1 : 0),
      active: current.active + (record.status === "watching" ? 1 : 0)
    }),
    { blocked: 0, needsReview: 0, active: 0 }
  );

  if (counts.blocked > 0) {
    return {
      totalRecords: records.length,
      ...counts,
      primaryMessage: `${counts.blocked} cockpit safety item${counts.blocked === 1 ? "" : "s"} blocked.`,
      nextAction: "Open the linked risk or approval artifact before continuing."
    };
  }

  if (counts.needsReview > 0) {
    return {
      totalRecords: records.length,
      ...counts,
      primaryMessage: `${counts.needsReview} cockpit item${counts.needsReview === 1 ? "" : "s"} ${
        counts.needsReview === 1 ? "needs" : "need"
      } review.`,
      nextAction: "Review approval and process records in priority order."
    };
  }

  const operationsSummary = summarizeOperations([...processes]);

  return {
    totalRecords: records.length,
    ...counts,
    primaryMessage: operationsSummary.primaryMessage,
    nextAction: operationsSummary.nextAction
  };
}

export function buildCockpitOpsSafetySnapshot(input: CockpitOpsSafetyInput): CockpitOpsSafetySnapshot {
  assertWorkspaceId(input.workspaceId);

  const artifacts = getCockpitArtifactsForWorkspace(input.workspaceId);
  const context: OpsSafetyBuildContext = {
    workspaceId: input.workspaceId,
    permissionMode: getPermissionMode(input.permissionModeId ?? DEFAULT_PERMISSION_MODE_ID),
    artifactsByKind: getArtifactsByKind(artifacts),
    approvals: input.approvals ?? [],
    processes: input.processes ?? [],
    now: input.now ?? Date.now()
  };

  const records = [
    createPermissionRecord(context),
    ...createApprovalRecords(context),
    ...createProcessRecords(context)
  ];

  return {
    workspaceId: context.workspaceId,
    permissionMode: context.permissionMode,
    summary: summarizeOpsSafety(records, context.processes),
    records,
    activityEvents: records.map((record) => createActivityEvent(record)),
    artifacts
  };
}

export function getCockpitOpsSafetyRecordsByArtifactId(
  records: ReadonlyArray<CockpitOpsSafetyRecord>,
  relatedArtifactId: string
): ReadonlyArray<CockpitOpsSafetyRecord> {
  return records.filter((record) => record.relatedArtifactId === relatedArtifactId);
}

export function getCockpitOpsSafetyRecordsByKind(
  records: ReadonlyArray<CockpitOpsSafetyRecord>,
  kind: CockpitOpsSafetyRecordKind
): ReadonlyArray<CockpitOpsSafetyRecord> {
  return records.filter((record) => record.kind === kind);
}
