/** API client for the Sub-Agent Spawner endpoints (P71). */

import { getRuntimeConfig } from "../../lib/api";
import type { ChildAgentConfig, ExecutionTreeData, WorkflowDefinition } from "./types";

function baseUrl(): string {
  return getRuntimeConfig().API_BASE_URL;
}

function headers(token: string | null, apiKey: string | null): Record<string, string> {
  const h: Record<string, string> = {
    Accept: "application/json",
    "Content-Type": "application/json",
  };
  if (token) {
    h.Authorization = `Bearer ${token}`;
  }
  if (apiKey) {
    h["X-API-Key"] = apiKey;
  }
  return h;
}

export async function fetchWorkflows(
  token: string | null,
  apiKey: string | null
): Promise<WorkflowDefinition[]> {
  const resp = await fetch(`${baseUrl()}/v1/spawner/workflows`, {
    headers: headers(token, apiKey),
  });
  if (!resp.ok) throw new Error(`Failed to list workflows: ${resp.status}`);
  return resp.json();
}

export async function fetchWorkflow(
  token: string | null,
  apiKey: string | null,
  workflowId: string
): Promise<WorkflowDefinition> {
  const resp = await fetch(
    `${baseUrl()}/v1/spawner/workflows/${encodeURIComponent(workflowId)}`,
    { headers: headers(token, apiKey) }
  );
  if (!resp.ok) throw new Error(`Failed to get workflow: ${resp.status}`);
  return resp.json();
}

export async function createWorkflow(
  token: string | null,
  apiKey: string | null,
  body: {
    name: string;
    description: string;
    parent_agent: string;
    children: ChildAgentConfig[];
  }
): Promise<WorkflowDefinition> {
  const resp = await fetch(`${baseUrl()}/v1/spawner/workflows`, {
    method: "POST",
    headers: headers(token, apiKey),
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`Failed to create workflow (${resp.status}): ${text}`);
  }
  return resp.json();
}

export async function deleteWorkflow(
  token: string | null,
  apiKey: string | null,
  workflowId: string
): Promise<void> {
  const resp = await fetch(
    `${baseUrl()}/v1/spawner/workflows/${encodeURIComponent(workflowId)}`,
    { method: "DELETE", headers: headers(token, apiKey) }
  );
  if (!resp.ok) throw new Error(`Failed to delete workflow: ${resp.status}`);
}

export async function executeWorkflow(
  token: string | null,
  apiKey: string | null,
  workflowId: string
): Promise<ExecutionTreeData> {
  const resp = await fetch(
    `${baseUrl()}/v1/spawner/workflows/${encodeURIComponent(workflowId)}/execute`,
    { method: "POST", headers: headers(token, apiKey) }
  );
  if (!resp.ok) throw new Error(`Failed to execute workflow: ${resp.status}`);
  return resp.json();
}

export async function fetchWorkflowStatus(
  token: string | null,
  apiKey: string | null,
  workflowId: string
): Promise<ExecutionTreeData> {
  const resp = await fetch(
    `${baseUrl()}/v1/spawner/workflows/${encodeURIComponent(workflowId)}/status`,
    { headers: headers(token, apiKey) }
  );
  if (!resp.ok) throw new Error(`Failed to fetch status: ${resp.status}`);
  return resp.json();
}

export async function fetchAgentNames(
  token: string | null,
  apiKey: string | null
): Promise<string[]> {
  const resp = await fetch(`${baseUrl()}/v1/agents/`, {
    headers: headers(token, apiKey),
  });
  if (!resp.ok) return [];
  const data: Array<{ name?: string }> = await resp.json();
  return data.map((a) => a.name ?? "").filter(Boolean);
}
