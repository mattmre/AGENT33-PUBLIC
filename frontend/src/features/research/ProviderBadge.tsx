/**
 * ProviderBadge: small badge showing the research provider name
 * with visual differentiation per provider.
 */

import type { ProviderBadgeProps } from "./CitationTypes";

/**
 * Provider display metadata. Maps provider_id to a human-friendly name
 * and a background color for visual differentiation.
 */
const PROVIDER_STYLES: Record<string, { label: string; color: string }> = {
  searxng: { label: "SearXNG", color: "#3a7bd5" },
  google: { label: "Google", color: "#4285f4" },
  bing: { label: "Bing", color: "#00897b" },
  duckduckgo: { label: "DuckDuckGo", color: "#de5833" },
  brave: { label: "Brave", color: "#fb542b" },
  tavily: { label: "Tavily", color: "#6c63ff" },
  serper: { label: "Serper", color: "#2d7d46" },
  jina: { label: "Jina", color: "#009688" },
  firecrawl: { label: "Firecrawl", color: "#ff6d00" },
};

const DEFAULT_STYLE = { label: "", color: "#607d8b" };

export function ProviderBadge({ providerId }: ProviderBadgeProps): JSX.Element {
  const style = PROVIDER_STYLES[providerId.toLowerCase()] ?? DEFAULT_STYLE;
  const label = style.label || providerId;

  return (
    <span
      className="provider-badge"
      data-testid="provider-badge"
      data-provider={providerId}
      style={{
        display: "inline-block",
        padding: "2px 8px",
        borderRadius: "12px",
        fontSize: "0.75em",
        fontWeight: 600,
        color: "#fff",
        backgroundColor: style.color,
        lineHeight: "1.4",
      }}
    >
      {label}
    </span>
  );
}
