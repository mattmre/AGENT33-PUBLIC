import { apiRequest } from "../../lib/api";
import type { ApiResult } from "../../types";
import type {
  OutcomeDashboardResponse,
  OutcomeEvent,
  OutcomeMetricType,
  OutcomeSummary,
  OutcomeTrend,
  SubmitIntakeRequest
} from "./types";

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isOutcomeTrend(value: unknown): value is OutcomeTrend {
  if (!isObject(value)) {
    return false;
  }
  return (
    typeof value.metric_type === "string" &&
    typeof value.domain === "string" &&
    typeof value.window === "number" &&
    typeof value.direction === "string" &&
    typeof value.sample_size === "number" &&
    Array.isArray(value.values) &&
    typeof value.previous_avg === "number" &&
    typeof value.current_avg === "number"
  );
}

function isOutcomeEvent(value: unknown): value is OutcomeEvent {
  if (!isObject(value)) {
    return false;
  }
  return (
    typeof value.id === "string" &&
    typeof value.tenant_id === "string" &&
    typeof value.domain === "string" &&
    typeof value.event_type === "string" &&
    typeof value.metric_type === "string" &&
    typeof value.value === "number" &&
    typeof value.occurred_at === "string" &&
    isObject(value.metadata)
  );
}

function isOutcomeSummary(value: unknown): value is OutcomeSummary {
  if (!isObject(value)) {
    return false;
  }
  return (
    typeof value.total_events === "number" &&
    Array.isArray(value.domains) &&
    Array.isArray(value.event_types) &&
    isObject(value.metric_counts)
  );
}

export function asOutcomeDashboardResponse(data: unknown): OutcomeDashboardResponse | null {
  if (!isObject(data)) {
    return null;
  }
  if (
    !Array.isArray(data.trends) ||
    !Array.isArray(data.recent_events) ||
    !isOutcomeSummary(data.summary)
  ) {
    return null;
  }
  const trends = data.trends.filter((item): item is OutcomeTrend => isOutcomeTrend(item));
  const recentEvents = data.recent_events.filter(
    (item): item is OutcomeEvent => isOutcomeEvent(item)
  );
  if (trends.length !== data.trends.length || recentEvents.length !== data.recent_events.length) {
    return null;
  }
  return {
    trends,
    recent_events: recentEvents,
    summary: data.summary
  };
}

export function asOutcomeTrend(data: unknown): OutcomeTrend | null {
  return isOutcomeTrend(data) ? data : null;
}

export async function fetchOutcomesDashboard(
  token: string,
  apiKey: string,
  domain: string,
  window: number
): Promise<ApiResult> {
  return apiRequest({
    method: "GET",
    path: "/v1/outcomes/dashboard",
    token,
    apiKey,
    query: {
      domain,
      window: String(window),
      recent_limit: "20"
    }
  });
}

export async function fetchOutcomeTrend(
  token: string,
  apiKey: string,
  metricType: OutcomeMetricType,
  domain: string,
  window: number
): Promise<ApiResult> {
  return apiRequest({
    method: "GET",
    path: "/v1/outcomes/trends/{metric_type}",
    pathParams: { metric_type: metricType },
    token,
    apiKey,
    query: {
      domain,
      window: String(window)
    }
  });
}

export async function submitImprovementIntake(
  token: string,
  apiKey: string,
  payload: SubmitIntakeRequest
): Promise<ApiResult> {
  return apiRequest({
    method: "POST",
    path: "/v1/improvements/intakes",
    token,
    apiKey,
    body: JSON.stringify(payload)
  });
}
