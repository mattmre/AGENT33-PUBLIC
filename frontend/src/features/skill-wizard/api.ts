import { apiRequest } from "../../lib/api";
import type { ApiResult } from "../../types";
import type { SkillDiscoveryResponse, SkillDraftRequest, SkillDraftResponse } from "./types";

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function asStringOrNull(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

export function asSkillDraftResponse(data: unknown): SkillDraftResponse | null {
  if (!isObject(data) || !isObject(data.skill)) {
    return null;
  }
  const skill = data.skill;
  if (
    typeof skill.name !== "string" ||
    typeof skill.description !== "string" ||
    !isStringArray(skill.allowed_tools) ||
    !isStringArray(skill.approval_required_for) ||
    !isStringArray(skill.tags) ||
    typeof skill.category !== "string" ||
    typeof skill.author !== "string" ||
    typeof data.markdown !== "string" ||
    typeof data.installed !== "boolean" ||
    !Array.isArray(data.warnings) ||
    !data.warnings.every((item) => typeof item === "string")
  ) {
    return null;
  }
  return {
    skill: {
      name: skill.name,
      description: skill.description,
      allowed_tools: skill.allowed_tools,
      approval_required_for: skill.approval_required_for,
      tags: skill.tags,
      category: skill.category,
      author: skill.author,
      command_name: asStringOrNull(skill.command_name)
    },
    markdown: data.markdown,
    installed: data.installed,
    path: asStringOrNull(data.path),
    warnings: data.warnings
  };
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
  if (matches.length !== data.matches.length) {
    return null;
  }
  return { query: data.query, matches };
}

export function createSkillDraft(
  body: SkillDraftRequest,
  token: string,
  apiKey: string
): Promise<ApiResult> {
  return apiRequest({
    method: "POST",
    path: "/v1/skills/authoring/drafts",
    token,
    apiKey,
    body: JSON.stringify(body)
  });
}

export function discoverSkills(query: string, token: string, apiKey: string): Promise<ApiResult> {
  return apiRequest({
    method: "GET",
    path: "/v1/discovery/skills",
    token,
    apiKey,
    query: {
      q: query,
      limit: "5"
    }
  });
}
