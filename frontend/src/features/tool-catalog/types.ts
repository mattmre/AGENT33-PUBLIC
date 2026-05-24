/** Types for the tool catalog feature. */

export interface CatalogEntry {
  name: string;
  description: string;
  provider: string;
  provider_name: string;
  category: string;
  version: string;
  enabled: boolean;
  has_schema: boolean;
  parameters_schema: Record<string, unknown>;
  result_schema: Record<string, unknown>;
  tags: string[];
  governance: Record<string, unknown>;
  owner: string;
  status: string;
  provenance: Record<string, unknown>;
  scope: Record<string, unknown>;
  approval: Record<string, unknown>;
  last_review: string;
  next_review: string;
  deprecation_message: string;
}

export interface CatalogPage {
  tools: CatalogEntry[];
  total: number;
  limit: number;
  offset: number;
}

export interface CategoryCount {
  category: string;
  count: number;
}

export interface ProviderCount {
  provider: string;
  count: number;
}

export interface CatalogSearchRequest {
  query?: string;
  categories?: string[];
  providers?: string[];
  tags?: string[];
  limit?: number;
  offset?: number;
}
