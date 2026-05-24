import { apiRequest } from "../../lib/api";
import type {
  PluginConfigRecord,
  PluginDetail,
  PluginDiscoverResponse,
  PluginDoctorReport,
  PluginDoctorSummary,
  PluginEventsResponse,
  PluginHealthResponse,
  PluginInstallResponse,
  PluginPermissionInventory,
  PluginSearchResponse,
  PluginSummary,
  PluginWorkspace
} from "./types";

function authArgs(token: string | null, apiKey: string | null): { token?: string; apiKey?: string } {
  return {
    token: token || undefined,
    apiKey: apiKey || undefined
  };
}

function extractErrorDetail(payload: unknown): string | null {
  if (!payload || typeof payload !== "object") {
    return null;
  }

  const record = payload as Record<string, unknown>;
  const detail = record.detail;
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  if (detail && typeof detail === "object") {
    const nested = detail as Record<string, unknown>;
    if (typeof nested.message === "string" && nested.message.trim()) {
      return nested.message;
    }
  }
  if (typeof record.message === "string" && record.message.trim()) {
    return record.message;
  }
  return null;
}

function requireOk<T>(data: unknown, ok: boolean, status: number, message: string): T {
  if (!ok) {
    throw new Error(`${message}: ${extractErrorDetail(data) ?? status}`);
  }
  return data as T;
}

async function getOptional<T>(
  token: string | null,
  apiKey: string | null,
  path: string,
  pathParams: Record<string, string>,
  message: string
): Promise<T | null> {
  const result = await apiRequest({
    method: "GET",
    path,
    pathParams,
    ...authArgs(token, apiKey)
  });

  if (!result.ok) {
    return null;
  }
  return result.data as T;
}

export async function fetchPlugins(
  token: string | null,
  apiKey: string | null
): Promise<PluginSummary[]> {
  const result = await apiRequest({
    method: "GET",
    path: "/v1/plugins",
    ...authArgs(token, apiKey)
  });
  return requireOk<PluginSummary[]>(result.data, result.ok, result.status, "Plugin list failed");
}

export async function searchPlugins(
  token: string | null,
  apiKey: string | null,
  query: string
): Promise<PluginSummary[]> {
  const result = await apiRequest({
    method: "GET",
    path: "/v1/plugins/search",
    query: { q: query },
    ...authArgs(token, apiKey)
  });
  const response = requireOk<PluginSearchResponse>(
    result.data,
    result.ok,
    result.status,
    "Plugin search failed"
  );
  return response.plugins;
}

export async function fetchPluginDoctorSummary(
  token: string | null,
  apiKey: string | null
): Promise<PluginDoctorSummary> {
  const result = await apiRequest({
    method: "GET",
    path: "/v1/plugins/doctor",
    ...authArgs(token, apiKey)
  });
  return requireOk<PluginDoctorSummary>(
    result.data,
    result.ok,
    result.status,
    "Plugin doctor summary failed"
  );
}

export async function fetchPluginWorkspace(
  token: string | null,
  apiKey: string | null,
  name: string
): Promise<PluginWorkspace> {
  const pathParams = { name };
  const detailResult = await apiRequest({
    method: "GET",
    path: "/v1/plugins/{name}",
    pathParams,
    ...authArgs(token, apiKey)
  });
  const detail = requireOk<PluginDetail>(
    detailResult.data,
    detailResult.ok,
    detailResult.status,
    "Plugin detail failed"
  );

  const [configResult, healthResult, permissionsResult, doctorResult, eventsResult] =
    await Promise.allSettled([
      getOptional<PluginConfigRecord>(
        token,
        apiKey,
        "/v1/plugins/{name}/config",
        pathParams,
        "Plugin config failed"
      ),
      getOptional<PluginHealthResponse>(
        token,
        apiKey,
        "/v1/plugins/{name}/health",
        pathParams,
        "Plugin health failed"
      ),
      getOptional<PluginPermissionInventory>(
        token,
        apiKey,
        "/v1/plugins/{name}/permissions",
        pathParams,
        "Plugin permissions failed"
      ),
      getOptional<PluginDoctorReport>(
        token,
        apiKey,
        "/v1/plugins/{name}/doctor",
        pathParams,
        "Plugin doctor failed"
      ),
      getOptional<PluginEventsResponse>(
        token,
        apiKey,
        "/v1/plugins/{name}/events",
        pathParams,
        "Plugin events failed"
      )
    ]);

  return {
    detail,
    config: configResult.status === "fulfilled" ? configResult.value ?? {} : {},
    health: healthResult.status === "fulfilled" ? healthResult.value : null,
    permissions: permissionsResult.status === "fulfilled" ? permissionsResult.value : null,
    doctor: doctorResult.status === "fulfilled" ? doctorResult.value : null,
    events: eventsResult.status === "fulfilled" ? eventsResult.value : null
  };
}

export async function enablePlugin(
  token: string | null,
  apiKey: string | null,
  name: string
): Promise<PluginSummary> {
  const result = await apiRequest({
    method: "POST",
    path: "/v1/plugins/{name}/enable",
    pathParams: { name },
    ...authArgs(token, apiKey)
  });
  return requireOk<PluginSummary>(result.data, result.ok, result.status, "Plugin enable failed");
}

export async function disablePlugin(
  token: string | null,
  apiKey: string | null,
  name: string
): Promise<PluginSummary> {
  const result = await apiRequest({
    method: "POST",
    path: "/v1/plugins/{name}/disable",
    pathParams: { name },
    ...authArgs(token, apiKey)
  });
  return requireOk<PluginSummary>(result.data, result.ok, result.status, "Plugin disable failed");
}

export async function reloadPlugin(
  token: string | null,
  apiKey: string | null,
  name: string
): Promise<PluginSummary> {
  const result = await apiRequest({
    method: "POST",
    path: "/v1/plugins/{name}/reload",
    pathParams: { name },
    ...authArgs(token, apiKey)
  });
  return requireOk<PluginSummary>(result.data, result.ok, result.status, "Plugin reload failed");
}

export async function updatePlugin(
  token: string | null,
  apiKey: string | null,
  name: string
): Promise<PluginInstallResponse> {
  const result = await apiRequest({
    method: "POST",
    path: "/v1/plugins/{name}/update",
    pathParams: { name },
    ...authArgs(token, apiKey)
  });
  return requireOk<PluginInstallResponse>(
    result.data,
    result.ok,
    result.status,
    "Plugin update failed"
  );
}

export async function installPlugin(
  token: string | null,
  apiKey: string | null,
  sourcePath: string,
  mode: "copy" | "link",
  enable: boolean | null
): Promise<PluginInstallResponse> {
  const result = await apiRequest({
    method: "POST",
    path: "/v1/plugins/install",
    body: JSON.stringify({
      source_path: sourcePath,
      mode,
      enable
    }),
    ...authArgs(token, apiKey)
  });
  return requireOk<PluginInstallResponse>(
    result.data,
    result.ok,
    result.status,
    "Plugin install failed"
  );
}

export async function linkPlugin(
  token: string | null,
  apiKey: string | null,
  name: string,
  sourcePath: string,
  enable: boolean | null
): Promise<PluginInstallResponse> {
  const result = await apiRequest({
    method: "POST",
    path: "/v1/plugins/{name}/link",
    pathParams: { name },
    body: JSON.stringify({
      source_path: sourcePath,
      mode: "link",
      enable
    }),
    ...authArgs(token, apiKey)
  });
  return requireOk<PluginInstallResponse>(result.data, result.ok, result.status, "Plugin link failed");
}

export async function discoverPlugins(
  token: string | null,
  apiKey: string | null
): Promise<PluginDiscoverResponse> {
  const result = await apiRequest({
    method: "POST",
    path: "/v1/plugins/discover",
    ...authArgs(token, apiKey)
  });
  return requireOk<PluginDiscoverResponse>(
    result.data,
    result.ok,
    result.status,
    "Plugin discovery failed"
  );
}

export async function savePluginConfig(
  token: string | null,
  apiKey: string | null,
  name: string,
  config: Record<string, unknown>,
  enabled: boolean | null,
  permissionOverrides: Record<string, boolean> | null
): Promise<PluginConfigRecord> {
  const result = await apiRequest({
    method: "PUT",
    path: "/v1/plugins/{name}/config",
    pathParams: { name },
    body: JSON.stringify({
      config,
      enabled,
      permission_overrides: permissionOverrides
    }),
    ...authArgs(token, apiKey)
  });
  return requireOk<PluginConfigRecord>(
    result.data,
    result.ok,
    result.status,
    "Plugin config save failed"
  );
}
