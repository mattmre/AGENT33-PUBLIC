import type { ApiResult, HttpMethod, RuntimeConfig } from "../types";

declare global {
  interface Window {
    __AGENT33_CONFIG__?: RuntimeConfig;
  }
}

interface ApiRequestArgs {
  method: HttpMethod;
  path: string;
  token?: string;
  apiKey?: string;
  pathParams?: Record<string, string>;
  query?: Record<string, string>;
  headers?: Record<string, string>;
  body?: string;
}

export function getRuntimeConfig(): RuntimeConfig {
  if (window.__AGENT33_CONFIG__?.API_BASE_URL) {
    return window.__AGENT33_CONFIG__;
  }
  return {
    API_BASE_URL: "http://localhost:8000"
  };
}

export function interpolatePath(
  template: string,
  pathParams: Record<string, string> = {}
): string {
  return template.replace(/\{([^}]+)\}/g, (_, key: string) => {
    const value = pathParams[key];
    return value !== undefined ? encodeURIComponent(value) : `{${key}}`;
  });
}

export function buildUrl(
  baseUrl: string,
  pathTemplate: string,
  pathParams: Record<string, string> = {},
  query: Record<string, string> = {}
): string {
  const resolvedPath = interpolatePath(pathTemplate, pathParams);
  const url = new URL(resolvedPath, ensureTrailingSlash(baseUrl));
  Object.entries(query).forEach(([k, v]) => {
    if (v.trim() !== "") {
      url.searchParams.set(k, v);
    }
  });
  return url.toString();
}

function ensureTrailingSlash(url: string): string {
  return url.endsWith("/") ? url : `${url}/`;
}

function parseBody(body?: string): unknown | undefined {
  if (!body || body.trim() === "") {
    return undefined;
  }
  return JSON.parse(body);
}

export async function apiRequest(args: ApiRequestArgs): Promise<ApiResult> {
  const { API_BASE_URL } = getRuntimeConfig();
  const url = buildUrl(API_BASE_URL, args.path, args.pathParams, args.query);
  const start = performance.now();

  const headers: Record<string, string> = {
    Accept: "application/json"
  };

  if (args.token) {
    headers.Authorization = `Bearer ${args.token}`;
  }
  if (args.apiKey) {
    headers["X-API-Key"] = args.apiKey;
  }

  const parsedBody = parseBody(args.body);
  if (parsedBody !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (args.headers) {
    Object.entries(args.headers).forEach(([key, value]) => {
      const normalizedValue = value.trim();
      if (normalizedValue !== "") {
        headers[key] = normalizedValue;
      }
    });
  }

  const response = await fetch(url, {
    method: args.method,
    headers,
    body: parsedBody !== undefined ? JSON.stringify(parsedBody) : undefined
  });

  const durationMs = Math.round(performance.now() - start);
  const contentType = response.headers.get("content-type") || "";
  let data: unknown = null;

  if (contentType.includes("application/json")) {
    data = await response.json();
  } else {
    data = await response.text();
  }

  return {
    status: response.status,
    durationMs,
    url,
    data,
    ok: response.ok
  };
}
