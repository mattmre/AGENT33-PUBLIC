export interface McpStatus {
  available: boolean;
  mcp_sdk_installed: boolean;
  transport_available: boolean;
  status?: string;
  agents_loaded?: number;
  tools_loaded?: number;
  skills_loaded?: number;
  workflows_loaded?: number;
  proxy_servers_loaded?: number;
  model_router_ready?: boolean;
  rag_pipeline_ready?: boolean;
}

export interface McpProxyServer {
  id: string;
  name: string;
  state: string;
  transport: string;
  tool_count: number;
  uptime_seconds: number;
  consecutive_failures: number;
  circuit_state: string;
  last_health_check: string | null;
  last_error: string | null;
}

export interface McpProxyServersResponse {
  servers: McpProxyServer[];
  total: number;
  healthy: number;
  degraded: number;
  unhealthy: number;
  stopped: number;
}

export interface McpProxyTool {
  name: string;
  description: string;
  proxy_server_id: string;
  original_name: string;
  inputSchema?: Record<string, unknown>;
}

export interface McpProxyToolsResponse {
  tools: McpProxyTool[];
  count: number;
}

export interface McpSyncEntry {
  target: string;
  config_path: string;
  present: boolean;
  matches: boolean;
  current: Record<string, unknown> | null;
  expected: Record<string, unknown> | null;
  error: string;
}

export interface McpSyncDiffResponse {
  entries: McpSyncEntry[];
}

export interface McpSyncPushResult {
  target: string;
  config_path: string;
  status: string;
  message: string;
  existing_entry: Record<string, unknown> | null;
}

export interface McpSyncPushResponse {
  results: McpSyncPushResult[];
}

export interface McpProxyValidateResponse {
  valid: boolean;
  server_count: number;
  errors: string[];
  diff: Record<string, unknown>;
}

export interface McpProxyReloadResponse {
  added?: string[];
  restarted?: string[];
  removed?: string[];
  unchanged?: string[];
  errors?: string[];
}

export interface EndpointState<T> {
  ok: boolean;
  status: number;
  data: T | null;
  error: string;
}

export interface McpHealthSnapshot {
  status: EndpointState<McpStatus>;
  proxyServers: EndpointState<McpProxyServersResponse>;
  proxyTools: EndpointState<McpProxyToolsResponse>;
  syncDiff: EndpointState<McpSyncDiffResponse>;
}
