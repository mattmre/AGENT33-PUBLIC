import { apiRequest } from "../../lib/api";
import type { ApiResult } from "../../types";
import type {
  SkillDiscoveryResponse,
  ToolDiscoveryResponse,
  WorkflowResolutionResponse
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

export function asToolDiscoveryResponse(data: unknown): ToolDiscoveryResponse | null {
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
        typeof item.status !== "string" ||
        typeof item.version !== "string" ||
        !isStringArray(item.tags)
      ) {
        return null;
      }
      return {
        name: item.name,
        description: item.description,
        score: item.score,
        status: item.status,
        version: item.version,
        tags: item.tags
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

export function discoverTools(query: string, token: string, apiKey: string): Promise<ApiResult> {
  return apiRequest({
    method: "GET",
    path: "/v1/discovery/tools",
    token,
    apiKey,
    query: { q: query, limit: "8" }
  });
}

export function discoverSkills(query: string, token: string, apiKey: string): Promise<ApiResult> {
  return apiRequest({
    method: "GET",
    path: "/v1/discovery/skills",
    token,
    apiKey,
    query: { q: query, limit: "8" }
  });
}

export function resolveWorkflows(query: string, token: string, apiKey: string): Promise<ApiResult> {
  return apiRequest({
    method: "GET",
    path: "/v1/discovery/workflows/resolve",
    token,
    apiKey,
    query: { q: query, limit: "8" }
  });
}
