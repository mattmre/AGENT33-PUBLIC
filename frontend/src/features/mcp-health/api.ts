import { apiRequest } from "../../lib/api";
import type { ApiResult } from "../../types";
import type {
  EndpointState,
  McpHealthSnapshot,
  McpProxyServer,
  McpProxyServersResponse,
  McpProxyReloadResponse,
  McpProxyTool,
  McpProxyToolsResponse,
  McpProxyValidateResponse,
  McpStatus,
  McpSyncDiffResponse,
  McpSyncEntry,
  McpSyncPushResponse,
  McpSyncPushResult
} from "./types";

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function asNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" ? value : fallback;
}

function asStringOrNull(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function isRecordOrNull(value: unknown): value is Record<string, unknown> | null {
  return value === null || isObject(value);
}

export function asMcpStatus(data: unknown): McpStatus | null {
  if (!isObject(data)) {
    return null;
  }
  if (
    typeof data.available !== "boolean" ||
    typeof data.mcp_sdk_installed !== "boolean" ||
    typeof data.transport_available !== "boolean"
  ) {
    return null;
  }
  return {
    available: data.available,
    mcp_sdk_installed: data.mcp_sdk_installed,
    transport_available: data.transport_available,
    status: typeof data.status === "string" ? data.status : undefined,
    agents_loaded: typeof data.agents_loaded === "number" ? data.agents_loaded : undefined,
    tools_loaded: typeof data.tools_loaded === "number" ? data.tools_loaded : undefined,
    skills_loaded: typeof data.skills_loaded === "number" ? data.skills_loaded : undefined,
    workflows_loaded: typeof data.workflows_loaded === "number" ? data.workflows_loaded : undefined,
    proxy_servers_loaded: typeof data.proxy_servers_loaded === "number" ? data.proxy_servers_loaded : undefined,
    model_router_ready: typeof data.model_router_ready === "boolean" ? data.model_router_ready : undefined,
    rag_pipeline_ready: typeof data.rag_pipeline_ready === "boolean" ? data.rag_pipeline_ready : undefined
  };
}

function asProxyServer(data: unknown): McpProxyServer | null {
  if (!isObject(data)) {
    return null;
  }
  if (
    typeof data.id !== "string" ||
    typeof data.name !== "string" ||
    typeof data.state !== "string" ||
    typeof data.transport !== "string" ||
    typeof data.tool_count !== "number"
  ) {
    return null;
  }
  return {
    id: data.id,
    name: data.name,
    state: data.state,
    transport: data.transport,
    tool_count: data.tool_count,
    uptime_seconds: asNumber(data.uptime_seconds),
    consecutive_failures: asNumber(data.consecutive_failures),
    circuit_state: typeof data.circuit_state === "string" ? data.circuit_state : "unknown",
    last_health_check: asStringOrNull(data.last_health_check),
    last_error: asStringOrNull(data.last_error)
  };
}

export function asProxyServersResponse(data: unknown): McpProxyServersResponse | null {
  if (!isObject(data) || !Array.isArray(data.servers)) {
    return null;
  }
  const servers = data.servers.map(asProxyServer);
  if (servers.some((server) => server === null)) {
    return null;
  }
  return {
    servers: servers as McpProxyServer[],
    total: asNumber(data.total, servers.length),
    healthy: asNumber(data.healthy),
    degraded: asNumber(data.degraded),
    unhealthy: asNumber(data.unhealthy),
    stopped: asNumber(data.stopped)
  };
}

function asProxyTool(data: unknown): McpProxyTool | null {
  if (!isObject(data)) {
    return null;
  }
  if (
    typeof data.name !== "string" ||
    typeof data.description !== "string" ||
    typeof data.proxy_server_id !== "string" ||
    typeof data.original_name !== "string"
  ) {
    return null;
  }
  return {
    name: data.name,
    description: data.description,
    proxy_server_id: data.proxy_server_id,
    original_name: data.original_name,
    inputSchema: isObject(data.inputSchema) ? data.inputSchema : undefined
  };
}

export function asProxyToolsResponse(data: unknown): McpProxyToolsResponse | null {
  if (!isObject(data) || !Array.isArray(data.tools)) {
    return null;
  }
  const tools = data.tools.map(asProxyTool);
  if (tools.some((tool) => tool === null)) {
    return null;
  }
  return {
    tools: tools as McpProxyTool[],
    count: asNumber(data.count, tools.length)
  };
}

function asSyncEntry(data: unknown): McpSyncEntry | null {
  if (!isObject(data)) {
    return null;
  }
  if (
    typeof data.target !== "string" ||
    typeof data.config_path !== "string" ||
    typeof data.present !== "boolean" ||
    typeof data.matches !== "boolean" ||
    !isRecordOrNull(data.current) ||
    !isRecordOrNull(data.expected) ||
    typeof data.error !== "string"
  ) {
    return null;
  }
  return {
    target: data.target,
    config_path: data.config_path,
    present: data.present,
    matches: data.matches,
    current: data.current,
    expected: data.expected,
    error: data.error
  };
}

export function asSyncDiffResponse(data: unknown): McpSyncDiffResponse | null {
  if (!isObject(data) || !Array.isArray(data.entries)) {
    return null;
  }
  const entries = data.entries.map(asSyncEntry);
  if (entries.some((entry) => entry === null)) {
    return null;
  }
  return { entries: entries as McpSyncEntry[] };
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string") ? value : [];
}

function asSyncPushResult(data: unknown): McpSyncPushResult | null {
  if (!isObject(data)) {
    return null;
  }
  if (
    typeof data.target !== "string" ||
    typeof data.config_path !== "string" ||
    typeof data.status !== "string"
  ) {
    return null;
  }
  return {
    target: data.target,
    config_path: data.config_path,
    status: data.status,
    message: typeof data.message === "string" ? data.message : "",
    existing_entry: isObject(data.existing_entry) ? data.existing_entry : null
  };
}

export function asSyncPushResponse(data: unknown): McpSyncPushResponse | null {
  if (!isObject(data) || !Array.isArray(data.results)) {
    return null;
  }
  const results = data.results.map(asSyncPushResult);
  if (results.some((result) => result === null)) {
    return null;
  }
  return { results: results as McpSyncPushResult[] };
}

export function asProxyValidateResponse(data: unknown): McpProxyValidateResponse | null {
  if (!isObject(data)) {
    return null;
  }
  if (typeof data.valid !== "boolean" || typeof data.server_count !== "number" || !Array.isArray(data.errors)) {
    return null;
  }
  return {
    valid: data.valid,
    server_count: data.server_count,
    errors: asStringArray(data.errors),
    diff: isObject(data.diff) ? data.diff : {}
  };
}

export function asProxyReloadResponse(data: unknown): McpProxyReloadResponse | null {
  if (!isObject(data)) {
    return null;
  }
  return {
    added: asStringArray(data.added),
    restarted: asStringArray(data.restarted),
    removed: asStringArray(data.removed),
    unchanged: asStringArray(data.unchanged),
    errors: asStringArray(data.errors)
  };
}

function endpointFromResult<T>(
  result: ApiResult,
  parser: (data: unknown) => T | null,
  label: string
): EndpointState<T> {
  if (!result.ok) {
    return {
      ok: false,
      status: result.status,
      data: null,
      error: `${label} failed (${result.status})`
    };
  }
  const data = parser(result.data);
  if (data === null) {
    return {
      ok: false,
      status: result.status,
      data: null,
      error: `${label} returned an unexpected response`
    };
  }
  return { ok: true, status: result.status, data, error: "" };
}

export async function fetchMcpHealthSnapshot(token: string, apiKey: string): Promise<{
  snapshot: McpHealthSnapshot;
  results: Array<[string, ApiResult]>;
}> {
  const [status, proxyServers, proxyTools, syncDiff] = await Promise.all([
    apiRequest({ method: "GET", path: "/v1/mcp/status", token, apiKey }),
    apiRequest({ method: "GET", path: "/v1/mcp/proxy/servers", token, apiKey }),
    apiRequest({ method: "GET", path: "/v1/mcp/proxy/tools", token, apiKey }),
    apiRequest({ method: "GET", path: "/v1/mcp/sync/diff", token, apiKey })
  ]);

  return {
    snapshot: {
      status: endpointFromResult(status, asMcpStatus, "MCP status"),
      proxyServers: endpointFromResult(proxyServers, asProxyServersResponse, "MCP proxy servers"),
      proxyTools: endpointFromResult(proxyTools, asProxyToolsResponse, "MCP proxy tools"),
      syncDiff: endpointFromResult(syncDiff, asSyncDiffResponse, "MCP sync diff")
    },
    results: [
      ["MCP Health - Status", status],
      ["MCP Health - Proxy Servers", proxyServers],
      ["MCP Health - Proxy Tools", proxyTools],
      ["MCP Health - Sync Diff", syncDiff]
    ]
  };
}

export function validateProxyConfig(token: string, apiKey: string): Promise<ApiResult> {
  return apiRequest({
    method: "POST",
    path: "/v1/mcp/proxy/validate-config",
    token,
    apiKey
  });
}

export function reloadProxyConfig(token: string, apiKey: string): Promise<ApiResult> {
  return apiRequest({
    method: "POST",
    path: "/v1/mcp/proxy/reload-config",
    token,
    apiKey
  });
}

export function pushMcpSync(
  targets: string[],
  force: boolean,
  token: string,
  apiKey: string
): Promise<ApiResult> {
  return apiRequest({
    method: "POST",
    path: "/v1/mcp/sync/push",
    token,
    apiKey,
    body: JSON.stringify({ targets, force })
  });
}
