import { apiRequest } from "../../lib/api";
import type { ApiResult } from "../../types";
import type { DailyActivity, InsightsReport, ModelUsage } from "./types";

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isModelUsage(value: unknown): value is ModelUsage {
  if (!isObject(value)) {
    return false;
  }
  return (
    typeof value.tokens === "number" &&
    typeof value.input_tokens === "number" &&
    typeof value.output_tokens === "number" &&
    typeof value.cost_usd === "number" &&
    typeof value.invocations === "number"
  );
}

function isDailyActivity(value: unknown): value is DailyActivity {
  if (!isObject(value)) {
    return false;
  }
  return (
    typeof value.date === "string" &&
    typeof value.sessions === "number" &&
    typeof value.tokens === "number" &&
    typeof value.cost_usd === "number"
  );
}

export function asInsightsReport(data: unknown): InsightsReport | null {
  if (!isObject(data)) {
    return null;
  }
  if (
    typeof data.total_sessions !== "number" ||
    typeof data.total_tokens !== "number" ||
    typeof data.total_cost_usd !== "number" ||
    typeof data.avg_session_duration_seconds !== "number" ||
    typeof data.period_days !== "number" ||
    typeof data.generated_at !== "string" ||
    !isObject(data.tool_usage) ||
    !isObject(data.model_usage) ||
    !Array.isArray(data.daily_activity)
  ) {
    return null;
  }

  // Validate tool_usage: all values must be numbers
  for (const val of Object.values(data.tool_usage)) {
    if (typeof val !== "number") {
      return null;
    }
  }

  // Validate model_usage: all values must be ModelUsage
  for (const val of Object.values(data.model_usage)) {
    if (!isModelUsage(val)) {
      return null;
    }
  }

  // Validate daily_activity entries
  const daily = data.daily_activity;
  for (const entry of daily) {
    if (!isDailyActivity(entry)) {
      return null;
    }
  }

  return {
    total_sessions: data.total_sessions as number,
    total_tokens: data.total_tokens as number,
    total_cost_usd: data.total_cost_usd as number,
    avg_session_duration_seconds: data.avg_session_duration_seconds as number,
    tool_usage: data.tool_usage as Record<string, number>,
    model_usage: data.model_usage as Record<string, ModelUsage>,
    daily_activity: data.daily_activity as DailyActivity[],
    period_days: data.period_days as number,
    generated_at: data.generated_at as string,
  };
}

export async function fetchInsights(
  token: string,
  apiKey: string,
  days: number = 30
): Promise<ApiResult> {
  return apiRequest({
    method: "GET",
    path: "/v1/insights",
    token,
    apiKey,
    query: {
      days: String(days),
    },
  });
}
