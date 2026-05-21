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
