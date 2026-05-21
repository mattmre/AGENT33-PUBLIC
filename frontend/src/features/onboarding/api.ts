import { apiRequest } from "../../lib/api";
import type { ApiResult } from "../../types";
import type { OnboardingStatus, OnboardingStep } from "./types";

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isOnboardingStep(value: unknown): value is OnboardingStep {
  if (!isObject(value)) {
    return false;
  }
  return (
    typeof value.step_id === "string" &&
    typeof value.category === "string" &&
    typeof value.title === "string" &&
    typeof value.description === "string" &&
    typeof value.completed === "boolean" &&
    typeof value.remediation === "string"
  );
}

export function asOnboardingStatus(data: unknown): OnboardingStatus | null {
  if (!isObject(data) || !Array.isArray(data.steps)) {
    return null;
  }
  if (
    typeof data.completed_count !== "number" ||
    typeof data.total_count !== "number" ||
    typeof data.overall_complete !== "boolean"
  ) {
    return null;
  }
  const steps = data.steps.filter(isOnboardingStep);
  if (steps.length !== data.steps.length) {
    return null;
  }
  return {
    steps,
    completed_count: data.completed_count,
    total_count: data.total_count,
    overall_complete: data.overall_complete
  };
}

export async function fetchOnboardingStatus(token: string, apiKey: string): Promise<ApiResult> {
  return apiRequest({
    method: "GET",
    path: "/v1/operator/onboarding",
    token,
    apiKey
  });
}
