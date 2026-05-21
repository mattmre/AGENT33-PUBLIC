/** API client for the tool catalog endpoints. */

import { getRuntimeConfig } from "../../lib/api";
import type {
  CatalogEntry,
  CatalogPage,
  CatalogSearchRequest,
  CategoryCount,
  ProviderCount,
} from "./types";

function baseUrl(): string {
  return getRuntimeConfig().API_BASE_URL;
}

function headers(token: string | null, apiKey: string | null): Record<string, string> {
  const h: Record<string, string> = { Accept: "application/json" };
  if (token) {
    h.Authorization = `Bearer ${token}`;
  }
  if (apiKey) {
    h["X-API-Key"] = apiKey;
  }
  return h;
}

export async function fetchCatalogTools(
  token: string | null,
  apiKey: string | null,
  params?: {
    category?: string;
    provider?: string;
    search?: string;
    limit?: number;
    offset?: number;
  }
): Promise<CatalogPage> {
  const url = new URL(`${baseUrl()}/v1/catalog/tools`);
  if (params?.category) url.searchParams.set("category", params.category);
  if (params?.provider) url.searchParams.set("provider", params.provider);
  if (params?.search) url.searchParams.set("search", params.search);
  if (params?.limit != null) url.searchParams.set("limit", String(params.limit));
  if (params?.offset != null) url.searchParams.set("offset", String(params.offset));

  const resp = await fetch(url.toString(), { headers: headers(token, apiKey) });
  if (!resp.ok) throw new Error(`Catalog list failed: ${resp.status}`);
  return resp.json();
}

export async function fetchToolDetail(
  token: string | null,
  apiKey: string | null,
  name: string
): Promise<CatalogEntry> {
  const resp = await fetch(`${baseUrl()}/v1/catalog/tools/${encodeURIComponent(name)}`, {
    headers: headers(token, apiKey),
  });
  if (!resp.ok) throw new Error(`Tool detail failed: ${resp.status}`);
  return resp.json();
}

export async function fetchToolSchema(
  token: string | null,
  apiKey: string | null,
  name: string
): Promise<Record<string, unknown>> {
  const resp = await fetch(
    `${baseUrl()}/v1/catalog/tools/${encodeURIComponent(name)}/schema`,
    { headers: headers(token, apiKey) }
  );
  if (!resp.ok) throw new Error(`Schema fetch failed: ${resp.status}`);
  return resp.json();
}

export async function fetchCategories(
  token: string | null,
  apiKey: string | null
): Promise<CategoryCount[]> {
  const resp = await fetch(`${baseUrl()}/v1/catalog/categories`, {
    headers: headers(token, apiKey),
  });
  if (!resp.ok) throw new Error(`Categories fetch failed: ${resp.status}`);
  return resp.json();
}

export async function fetchProviders(
  token: string | null,
  apiKey: string | null
): Promise<ProviderCount[]> {
  const resp = await fetch(`${baseUrl()}/v1/catalog/providers`, {
    headers: headers(token, apiKey),
  });
  if (!resp.ok) throw new Error(`Providers fetch failed: ${resp.status}`);
  return resp.json();
}

export async function searchCatalog(
  token: string | null,
  apiKey: string | null,
  body: CatalogSearchRequest
): Promise<CatalogPage> {
  const resp = await fetch(`${baseUrl()}/v1/catalog/search`, {
    method: "POST",
    headers: { ...headers(token, apiKey), "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`Catalog search failed: ${resp.status}`);
  return resp.json();
}
