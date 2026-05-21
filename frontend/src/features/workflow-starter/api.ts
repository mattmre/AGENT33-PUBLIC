import { apiRequest } from "../../lib/api";
import { asRecord, readNumber, readString } from "../../lib/valueReaders";
import type { ApiResult } from "../../types";
import { asOnboardingStatus } from "../onboarding/api";
import type {
  SkillDiscoveryResponse,
  WorkflowStarterModelHealth,
  WorkflowStarterModelHealthProvider,
  WorkflowCreateResponse,
  WorkflowResolutionResponse,
  WorkflowStarterSessionSummary,
  WorkflowStarterRequest
} from "./types";

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function asStringOrNull(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

export function asWorkflowCreateResponse(data: unknown): WorkflowCreateResponse | null {
  if (!isObject(data)) {
    return null;
  }
  if (
    typeof data.name !== "string" ||
    typeof data.version !== "string" ||
    typeof data.step_count !== "number" ||
    typeof data.created !== "boolean"
  ) {
    return null;
  }
  return {
    name: data.name,
    version: data.version,
    step_count: data.step_count,
    created: data.created
  };
}

export function asWorkflowResolutionResponse(data: unknown): WorkflowResolutionResponse | null {
  if (!isObject(data) || typeof data.query !== "string" || !Array.isArray(data.matches)) {
    return null;
  }
  const matches = data.matches
    .map((item) => {
      if (!isObject(item)) {
        return null;
      }
      if (
        typeof item.name !== "string" ||
        typeof item.description !== "string" ||
        typeof item.score !== "number" ||
        typeof item.source !== "string" ||
        typeof item.version !== "string" ||
        !isStringArray(item.tags) ||
        typeof item.source_path !== "string"
      ) {
        return null;
      }
      return {
        name: item.name,
        description: item.description,
        score: item.score,
        source: item.source,
        version: item.version,
        tags: item.tags,
        source_path: item.source_path,
        pack: asStringOrNull(item.pack)
      };
    })
    .filter((item): item is NonNullable<typeof item> => item !== null);
  return matches.length === data.matches.length ? { query: data.query, matches } : null;
}

export function asSkillDiscoveryResponse(data: unknown): SkillDiscoveryResponse | null {
  if (!isObject(data) || typeof data.query !== "string" || !Array.isArray(data.matches)) {
    return null;
  }
  const matches = data.matches
    .map((item) => {
      if (!isObject(item)) {
        return null;
      }
      if (
        typeof item.name !== "string" ||
        typeof item.description !== "string" ||
        typeof item.score !== "number" ||
        typeof item.version !== "string" ||
        !isStringArray(item.tags)
      ) {
        return null;
      }
      return {
        name: item.name,
        description: item.description,
        score: item.score,
        version: item.version,
        tags: item.tags,
        pack: asStringOrNull(item.pack)
      };
    })
    .filter((item): item is NonNullable<typeof item> => item !== null);
  return matches.length === data.matches.length ? { query: data.query, matches } : null;
}

export function asWorkflowStarterOnboardingStatus(data: unknown) {
  return asOnboardingStatus(data);
}

export function asWorkflowStarterModelHealth(data: unknown): WorkflowStarterModelHealth | null {
  const root = asRecord(data);
  const providers = Array.isArray(root.providers)
    ? root.providers
        .map(asWorkflowStarterModelHealthProvider)
        .filter((provider): provider is WorkflowStarterModelHealthProvider => provider !== null)
    : [];
  const overallState = readString(root.overall_state);
  if (
    overallState !== "ready" &&
    overallState !== "needs_attention" &&
    overallState !== "unavailable"
  ) {
    return null;
  }

  return {
    overallState,
    summary: readString(root.summary) || "Model readiness data is unavailable.",
    readyProviderCount: readNumber(root.ready_provider_count) ?? 0,
    attentionProviderCount: readNumber(root.attention_provider_count) ?? 0,
    totalModelCount: readNumber(root.total_model_count) ?? 0,
    providers
  };
}

function asWorkflowStarterModelHealthProvider(
  data: unknown
): WorkflowStarterModelHealthProvider | null {
  const root = asRecord(data);
  const state = readString(root.state);
  if (
    state !== "available" &&
    state !== "empty" &&
    state !== "unavailable" &&
    state !== "error"
  ) {
    return null;
  }

  return {
    provider: readString(root.provider),
    label: readString(root.label) || "Local provider",
    state,
    ok: root.ok === true,
    baseUrl: readString(root.base_url),
    modelCount: readNumber(root.model_count) ?? 0,
    message: readString(root.message) || "Provider readiness is unavailable.",
    action: readString(root.action) || "Refresh local model health after checking this runtime."
  };
}

export function asWorkflowStarterSessionSummaries(
  data: unknown
): WorkflowStarterSessionSummary[] | null {
  if (!Array.isArray(data)) {
    return null;
  }

  const sessions = data
    .map((item) => {
      const root = asRecord(item);
      if (
        readString(root.session_id) === "" ||
        readString(root.status) === "" ||
        readString(root.started_at) === "" ||
        readString(root.updated_at) === ""
      ) {
        return null;
      }
      return {
        session_id: readString(root.session_id),
        purpose: readString(root.purpose),
        status: readString(root.status),
        started_at: readString(root.started_at),
        updated_at: readString(root.updated_at),
        ended_at: typeof root.ended_at === "string" ? root.ended_at : null,
        task_count: readNumber(root.task_count) ?? 0,
        tasks_completed: readNumber(root.tasks_completed) ?? 0,
        event_count: readNumber(root.event_count) ?? 0,
        parent_session_id: typeof root.parent_session_id === "string" ? root.parent_session_id : null,
        tenant_id: readString(root.tenant_id)
      };
    })
    .filter((session): session is WorkflowStarterSessionSummary => session !== null);

  return sessions.length === data.length ? sessions : null;
}

export function resolveWorkflows(query: string, token: string, apiKey: string): Promise<ApiResult> {
  return apiRequest({
    method: "GET",
    path: "/v1/discovery/workflows/resolve",
    token,
    apiKey,
    query: { q: query, limit: "5" }
  });
}

export function discoverSkills(query: string, token: string, apiKey: string): Promise<ApiResult> {
  return apiRequest({
    method: "GET",
    path: "/v1/discovery/skills",
    token,
    apiKey,
    query: { q: query, limit: "5" }
  });
}

export function fetchWorkflowStarterReadiness(token: string, apiKey: string): Promise<ApiResult> {
  return apiRequest({
    method: "GET",
    path: "/v1/operator/onboarding",
    token,
    apiKey
  });
}

export function fetchWorkflowStarterModelHealth(token: string, apiKey: string): Promise<ApiResult> {
  return apiRequest({
    method: "GET",
    path: "/v1/model-health",
    token,
    apiKey
  });
}

export function fetchWorkflowStarterIncompleteSessions(
  token: string,
  apiKey: string
): Promise<ApiResult> {
  return apiRequest({
    method: "GET",
    path: "/v1/sessions/incomplete",
    token,
    apiKey
  });
}

export function createWorkflow(
  body: WorkflowStarterRequest,
  token: string,
  apiKey: string
): Promise<ApiResult> {
  return apiRequest({
    method: "POST",
    path: "/v1/workflows/",
    token,
    apiKey,
    body: JSON.stringify(body)
  });
}
