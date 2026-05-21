import type {
  CockpitOpsSafetyRecord,
  CockpitOpsSafetyRecordStatus,
  CockpitOpsSafetySnapshot
} from "./cockpitOpsSafety";
import type { PermissionModeId } from "./permissionModes";
import { getPermissionMode } from "./permissionModes";

export interface SafetyGateCounts {
  readonly blocked: number;
  readonly needsReview: number;
  readonly watching: number;
  readonly clear: number;
}

export interface SafetyRecordGroup {
  readonly status: CockpitOpsSafetyRecordStatus;
  readonly heading: string;
  readonly description: string;
  readonly records: ReadonlyArray<CockpitOpsSafetyRecord>;
}

export interface SafetyGateCta {
  readonly label: string;
  readonly intent: "primary" | "warning" | "danger";
}

const SAFETY_STATUS_ORDER: ReadonlyArray<CockpitOpsSafetyRecordStatus> = [
  "blocked",
  "needs-review",
  "watching",
  "clear"
];

const SAFETY_STATUS_LABELS: Record<CockpitOpsSafetyRecordStatus, string> = {
  blocked: "Blocked",
  "needs-review": "Needs review",
  watching: "Watching",
  clear: "Clear"
};

const SAFETY_GROUP_DESCRIPTIONS: Record<CockpitOpsSafetyRecordStatus, string> = {
  blocked: "Resolve these gates before running or shipping this work.",
  "needs-review": "These items need an operator decision before AGENT33 continues.",
  watching: "These items can keep moving, but AGENT33 is still watching for risk.",
  clear: "These records are safe to keep as review evidence."
};

export function formatGateLabel(value: string): string {
  return value.replace(/-/g, " ");
}

export function getSafetyStatusLabel(status: CockpitOpsSafetyRecordStatus): string {
  return SAFETY_STATUS_LABELS[status];
}

export function countSafetyGateRecords(records: ReadonlyArray<CockpitOpsSafetyRecord>): SafetyGateCounts {
  return records.reduce(
    (counts, record) => ({
      blocked: counts.blocked + (record.status === "blocked" ? 1 : 0),
      needsReview: counts.needsReview + (record.status === "needs-review" ? 1 : 0),
      watching: counts.watching + (record.status === "watching" ? 1 : 0),
      clear: counts.clear + (record.status === "clear" ? 1 : 0)
    }),
    { blocked: 0, needsReview: 0, watching: 0, clear: 0 }
  );
}

export function groupSafetyRecordsByStatus(
  records: ReadonlyArray<CockpitOpsSafetyRecord>
): ReadonlyArray<SafetyRecordGroup> {
  return SAFETY_STATUS_ORDER.map((status) => ({
    status,
    heading: getSafetyStatusLabel(status),
    description: SAFETY_GROUP_DESCRIPTIONS[status],
    records: records.filter((record) => record.status === status)
  })).filter((group) => group.records.length > 0);
}

export function getTopSafetyGateRecords(
  records: ReadonlyArray<CockpitOpsSafetyRecord>,
  limit = 3
): ReadonlyArray<CockpitOpsSafetyRecord> {
  return records
    .map((record, originalIndex) => ({ record, originalIndex }))
    .sort((left, right) => {
      const statusDelta = SAFETY_STATUS_ORDER.indexOf(left.record.status) - SAFETY_STATUS_ORDER.indexOf(right.record.status);
      return statusDelta === 0 ? left.originalIndex - right.originalIndex : statusDelta;
    })
    .slice(0, limit)
    .map((entry) => entry.record);
}

export function getSafetyGateCta(
  snapshot: CockpitOpsSafetySnapshot,
  permissionModeId: PermissionModeId
): SafetyGateCta {
  const permissionMode = getPermissionMode(permissionModeId);

  if (snapshot.summary.blocked > 0) {
    return {
      label: permissionMode.id === "restricted" ? "Unlock a safer mode" : "Resolve blocked items",
      intent: "danger"
    };
  }

  if (snapshot.summary.needsReview > 0) {
    return { label: "Review approvals", intent: "warning" };
  }

  if (snapshot.summary.active > 0) {
    return { label: "Monitor safety signals", intent: "primary" };
  }

  return { label: "Review safety status", intent: "primary" };
}
