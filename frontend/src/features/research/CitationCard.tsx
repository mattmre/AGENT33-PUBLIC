/**
 * CitationCard: renders a single web research citation with trust indicator,
 * provider badge, snippet text, and expandable preview section.
 */

import { useState } from "react";

import type { CitationCardProps } from "./CitationTypes";
import { trustLevelLabel, trustLevelToDisplayTier } from "./CitationTypes";
import { ProviderBadge } from "./ProviderBadge";

/** CSS color for each display tier. */
const TRUST_COLORS: Record<string, string> = {
  high: "#4caf50",
  medium: "#ff9800",
  low: "#f44336",
};

export function CitationCard({
  citation,
  snippet,
  publishedAt,
}: CitationCardProps): JSX.Element {
  const [expanded, setExpanded] = useState(false);

  const displayTier = trustLevelToDisplayTier(citation.trust_level);
  const trustColor = TRUST_COLORS[displayTier];
  const trustLabel = trustLevelLabel(citation.trust_level);

  return (
    <article
      className="citation-card"
      data-testid="citation-card"
      style={{
        border: "1px solid #ddd",
        borderLeft: `4px solid ${trustColor}`,
        borderRadius: "5px",
        padding: "12px 15px",
        marginBottom: "10px",
        backgroundColor: "#fff",
      }}
    >
      {/* Header row: title + provider badge */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: "8px",
        }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          <a
            href={citation.url}
            target="_blank"
            rel="noopener noreferrer"
            className="citation-title"
            style={{
              fontSize: "1em",
              fontWeight: 600,
              color: "#1a0dab",
              textDecoration: "none",
              wordBreak: "break-word",
            }}
          >
            {citation.title}
          </a>
          <div
            className="citation-display-url"
            style={{ fontSize: "0.8em", color: "#006621", marginTop: "2px" }}
          >
            {citation.display_url}
          </div>
        </div>
        <ProviderBadge providerId={citation.provider_id} />
      </div>

      {/* Snippet */}
      {snippet && (
        <p
          className="citation-snippet"
          style={{ margin: "8px 0 4px", fontSize: "0.9em", color: "#333" }}
        >
          {snippet}
        </p>
      )}

      {/* Meta row: trust indicator + published date */}
      <div
        className="citation-meta"
        style={{
          display: "flex",
          alignItems: "center",
          gap: "10px",
          marginTop: "6px",
          fontSize: "0.8em",
        }}
      >
        <span
          className="trust-indicator"
          data-testid="trust-indicator"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "4px",
          }}
        >
          <span
            aria-hidden="true"
            style={{
              display: "inline-block",
              width: "8px",
              height: "8px",
              borderRadius: "50%",
              backgroundColor: trustColor,
            }}
          />
          <span style={{ color: trustColor, fontWeight: 500 }}>{trustLabel}</span>
        </span>

        {publishedAt && (
          <span className="citation-date" style={{ color: "#999" }}>
            {formatDate(publishedAt)}
          </span>
        )}

        <span className="citation-domain" style={{ color: "#666" }}>
          {citation.domain}
        </span>
      </div>

      {/* Expandable preview: shows trust reason */}
      <div style={{ marginTop: "6px" }}>
        <button
          className="citation-expand-toggle"
          data-testid="expand-toggle"
          onClick={() => setExpanded(!expanded)}
          aria-expanded={expanded}
          style={{
            background: "none",
            border: "none",
            color: "#1a73e8",
            cursor: "pointer",
            padding: 0,
            fontSize: "0.8em",
          }}
        >
          {expanded ? "Hide details" : "Show details"}
        </button>

        {expanded && (
          <div
            className="citation-preview"
            data-testid="citation-preview"
            style={{
              marginTop: "6px",
              padding: "8px 10px",
              backgroundColor: "#f5f5f5",
              borderRadius: "4px",
              fontSize: "0.85em",
              color: "#555",
            }}
          >
            <strong>Trust reason:</strong> {citation.trust_reason}
          </div>
        )}
      </div>
    </article>
  );
}

/** Format an ISO date string into a short readable format. */
function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}
