const BASE_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? "";

export interface LiveSession {
  id: string;
  status: string;
}

export interface LiveWorkflowRun {
  id: string;
  status: string;
}

export interface LiveAgent {
  id: string;
  name: string;
  status: string;
}

export async function fetchLiveSessions(token: string): Promise<LiveSession[]> {
  try {
    const res = await fetch(`${BASE_URL}/v1/sessions`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (!res.ok) return [];
    const data: unknown = await res.json();
    return Array.isArray(data) ? (data as LiveSession[]) : ((data as { items?: LiveSession[] }).items ?? []);
  } catch {
    return [];
  }
}

export async function fetchLiveWorkflowRuns(token: string): Promise<LiveWorkflowRun[]> {
  try {
    const res = await fetch(`${BASE_URL}/v1/workflows/runs`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (!res.ok) return [];
    const data: unknown = await res.json();
    return Array.isArray(data)
      ? (data as LiveWorkflowRun[])
      : ((data as { items?: LiveWorkflowRun[] }).items ?? []);
  } catch {
    return [];
  }
}

export async function fetchLiveAgents(token: string): Promise<LiveAgent[]> {
  try {
    const res = await fetch(`${BASE_URL}/v1/agents`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (!res.ok) return [];
    const data: unknown = await res.json();
    return Array.isArray(data) ? (data as LiveAgent[]) : ((data as { items?: LiveAgent[] }).items ?? []);
  } catch {
    return [];
  }
}
