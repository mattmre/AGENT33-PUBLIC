import { apiRequest } from "../../lib/api";
import type { ApiResult } from "../../types";
import type { DoctorStatusResponse } from "./types";

function isSeverity(value: unknown): value is DoctorStatusResponse["overall"] {
  return value === "ok" || value === "warning" || value === "error";
}

export function asDoctorStatusResponse(value: unknown): DoctorStatusResponse | null {
  if (typeof value !== "object" || value === null) {
    return null;
  }
  const record = value as Record<string, unknown>;
  if (!isSeverity(record.overall) || typeof record.generated_at !== "string") {
    return null;
  }
  if (!Array.isArray(record.findings)) {
    return null;
  }
  const findings = record.findings.flatMap((item) => {
    if (typeof item !== "object" || item === null) {
      return [];
    }
    const finding = item as Record<string, unknown>;
    if (
      typeof finding.id !== "string" ||
      typeof finding.category !== "string" ||
      !isSeverity(finding.severity) ||
      typeof finding.owner !== "string" ||
      typeof finding.message !== "string" ||
      typeof finding.fix_action !== "string"
    ) {
      return [];
    }
    return [
      {
        id: finding.id,
        category: finding.category,
        severity: finding.severity,
        owner: finding.owner,
        message: finding.message,
        fix_action: finding.fix_action,
        stale_age_seconds:
          typeof finding.stale_age_seconds === "number" ? finding.stale_age_seconds : 0,
        evidence_refs: Array.isArray(finding.evidence_refs)
          ? finding.evidence_refs.filter((ref): ref is string => typeof ref === "string")
          : []
      }
    ];
  });
  return {
    overall: record.overall,
    generated_at: record.generated_at,
    findings
  };
}

export function fetchDoctorStatus(token: string, apiKey: string): Promise<ApiResult> {
  return apiRequest({
    method: "GET",
    path: "/v1/doctor/status",
    token,
    apiKey
  });
}
