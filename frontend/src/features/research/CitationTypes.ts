/**
 * TypeScript types for web research citations.
 *
 * Trust levels match the backend ResearchTrustLevel enum exactly.
 * The trustLevelDisplay mapping provides visual presentation semantics.
 */

/** Trust levels as defined by the backend ResearchTrustLevel StrEnum. */
export type TrustLevel = "search-indexed" | "fetch-verified" | "blocked";

/** Display-tier mapping for color-coding trust indicators. */
export type TrustDisplayTier = "high" | "medium" | "low";

/**
 * A single web research citation, matching the backend
 * WebResearchCitation model from engine/src/agent33/web_research/models.py.
 */
export interface Citation {
  title: string;
  url: string;
  display_url: string;
  domain: string;
  provider_id: string;
  trust_level: TrustLevel;
  trust_reason: string;
}

/**
 * A full web research result, matching the backend WebResearchResult model.
 * Includes an embedded citation for rendering.
 */
export interface WebResearchResult {
  title: string;
  url: string;
  snippet: string;
  provider_id: string;
  rank: number;
  domain: string;
  display_url: string;
  trust_level: TrustLevel;
  trust_reason: string;
  citation: Citation;
}

/** Props for the CitationCard component. */
export interface CitationCardProps {
  citation: Citation;
  /** Optional snippet text from the parent WebResearchResult. */
  snippet?: string;
  /** Optional published date string (ISO 8601). */
  publishedAt?: string;
}

/** Sort mode for the citation list. */
export type CitationSortMode = "date" | "trust" | "relevance";

/** Props for the CitationList component. */
export interface CitationListProps {
  citations: WebResearchResult[];
  sortBy?: CitationSortMode;
  groupByProvider?: boolean;
}

/** Props for the ProviderBadge component. */
export interface ProviderBadgeProps {
  providerId: string;
}

/**
 * Map backend trust levels to display tiers for color-coding.
 * - fetch-verified = high (green): content was actually retrieved and verified
 * - search-indexed = medium (yellow): appeared in search results but not fetched
 * - blocked = low (red): fetch was blocked by policy or error
 */
export function trustLevelToDisplayTier(level: TrustLevel): TrustDisplayTier {
  switch (level) {
    case "fetch-verified":
      return "high";
    case "search-indexed":
      return "medium";
    case "blocked":
      return "low";
  }
}

/**
 * Human-readable label for a trust level.
 */
export function trustLevelLabel(level: TrustLevel): string {
  switch (level) {
    case "fetch-verified":
      return "Verified";
    case "search-indexed":
      return "Indexed";
    case "blocked":
      return "Blocked";
  }
}

/** Trust display tier sort priority (higher = more trusted, sorts first). */
const TRUST_SORT_PRIORITY: Record<TrustLevel, number> = {
  "fetch-verified": 3,
  "search-indexed": 2,
  blocked: 1,
};

/**
 * Sort comparator for trust level (highest trust first).
 */
export function compareTrustLevel(a: TrustLevel, b: TrustLevel): number {
  return TRUST_SORT_PRIORITY[b] - TRUST_SORT_PRIORITY[a];
}
