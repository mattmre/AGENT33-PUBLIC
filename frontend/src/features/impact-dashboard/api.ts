import { apiRequest } from "../../lib/api";
import type { ApiResult } from "../../types";
import type {
  DashboardResponse,
  FailureModeStat,
  OutcomeSummary,
  PackImpactResponse,
  ROIResponse,
  WeekOverWeekStat,
} from "./types";

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isWeekOverWeekStat(value: unknown): value is WeekOverWeekStat {
  if (!isObject(value)) return false;
  return (
    typeof value.metric_type === "string" &&
    typeof value.current_week_avg === "number" &&
    typeof value.previous_week_avg === "number" &&
    typeof value.pct_change === "number"
  );
}

function isFailureModeStat(value: unknown): value is FailureModeStat {
  if (!isObject(value)) return false;
  return typeof value.failure_class === "string" && typeof value.count === "number";
}

function isOutcomeSummary(value: unknown): value is OutcomeSummary {
  if (!isObject(value)) return false;
  return (
    typeof value.total_events === "number" &&
    Array.isArray(value.domains) &&
    Array.isArray(value.event_types) &&
    isObject(value.metric_counts)
  );
}

export function asDashboardResponse(data: unknown): DashboardResponse | null {
  if (!isObject(data)) return null;
  if (!isOutcomeSummary(data.summary)) return null;
  const wow = Array.isArray(data.week_over_week)
    ? data.week_over_week.filter((w): w is WeekOverWeekStat => isWeekOverWeekStat(w))
    : [];
  const failures = Array.isArray(data.top_failure_modes)
    ? data.top_failure_modes.filter((f): f is FailureModeStat => isFailureModeStat(f))
    : [];
  return {
    summary: data.summary,
    week_over_week: wow,
    top_failure_modes: failures,
  };
}

export function asROIResponse(data: unknown): ROIResponse | null {
  if (!isObject(data)) return null;
  if (
    typeof data.total_invocations !== "number" ||
    typeof data.success_count !== "number" ||
    typeof data.failure_count !== "number" ||
    typeof data.estimated_hours_saved !== "number" ||
    typeof data.estimated_value_usd !== "number" ||
    typeof data.success_rate !== "number" ||
    typeof data.avg_latency_ms !== "number"
  ) {
    return null;
  }
  return {
    total_invocations: data.total_invocations,
    success_count: data.success_count,
    failure_count: data.failure_count,
    estimated_hours_saved: data.estimated_hours_saved,
    estimated_value_usd: data.estimated_value_usd,
    success_rate: data.success_rate,
    avg_latency_ms: data.avg_latency_ms,
  };
}

export function asPackImpactResponse(data: unknown): PackImpactResponse | null {
  if (!isObject(data)) return null;
  if (!Array.isArray(data.packs)) return null;
  return { packs: data.packs as PackImpactResponse["packs"] };
}

export async function fetchDashboard(
  token: string,
  apiKey: string,
): Promise<ApiResult> {
  return apiRequest({
    method: "GET",
    path: "/v1/outcomes/dashboard",
    token,
    apiKey,
    query: { recent_limit: "5" },
  });
}

export async function fetchROI(
  token: string,
  apiKey: string,
  domain: string,
  hoursSaved: number,
  costPerHour: number,
  windowDays: number,
): Promise<ApiResult> {
  return apiRequest({
    method: "POST",
    path: "/v1/outcomes/roi",
    token,
    apiKey,
    body: JSON.stringify({
      domain,
      hours_saved_per_success: hoursSaved,
      cost_per_hour_usd: costPerHour,
      window_days: windowDays,
    }),
  });
}

export async function fetchPackImpact(
  token: string,
  apiKey: string,
): Promise<ApiResult> {
  return apiRequest({
    method: "GET",
    path: "/v1/outcomes/pack-impact",
    token,
    apiKey,
  });
}
