/**
 * CitationList: renders a sortable, optionally grouped list of CitationCards
 * from web research results.
 */

import { useMemo, useState } from "react";

import { CitationCard } from "./CitationCard";
import type {
  CitationListProps,
  CitationSortMode,
  WebResearchResult,
} from "./CitationTypes";
import { compareTrustLevel } from "./CitationTypes";

/**
 * Sort results by the selected mode.
 * - "relevance": by rank (ascending, lower rank = more relevant)
 * - "trust": by trust level (highest first)
 * - "date": not directly available on the model, so falls back to rank
 */
function sortResults(
  results: WebResearchResult[],
  mode: CitationSortMode,
): WebResearchResult[] {
  const sorted = [...results];
  switch (mode) {
    case "trust":
      sorted.sort((a, b) => compareTrustLevel(a.trust_level, b.trust_level));
      break;
    case "relevance":
      sorted.sort((a, b) => a.rank - b.rank);
      break;
    case "date":
      // No published_at on the model; stable sort by rank as fallback
      sorted.sort((a, b) => a.rank - b.rank);
      break;
  }
  return sorted;
}

/**
 * Group results by provider_id while preserving sort order within groups.
 */
function groupByProvider(
  results: WebResearchResult[],
): Map<string, WebResearchResult[]> {
  const groups = new Map<string, WebResearchResult[]>();
  for (const r of results) {
    const group = groups.get(r.provider_id);
    if (group) {
      group.push(r);
    } else {
      groups.set(r.provider_id, [r]);
    }
  }
  return groups;
}

const SORT_LABELS: Record<CitationSortMode, string> = {
  relevance: "Relevance",
  trust: "Trust Level",
  date: "Date",
};

export function CitationList({
  citations,
  sortBy: initialSort = "relevance",
  groupByProvider: initialGroup = false,
}: CitationListProps): JSX.Element {
  const [sortMode, setSortMode] = useState<CitationSortMode>(initialSort);
  const [grouped, setGrouped] = useState(initialGroup);

  const sorted = useMemo(() => sortResults(citations, sortMode), [citations, sortMode]);

  if (citations.length === 0) {
    return (
      <div className="citation-list-empty" data-testid="citation-list-empty">
        <p style={{ color: "#888", fontStyle: "italic" }}>
          No citations available.
        </p>
      </div>
    );
  }

  return (
    <div className="citation-list" data-testid="citation-list">
      {/* Sort and group controls */}
      <div
        className="citation-list-controls"
        style={{
          display: "flex",
          alignItems: "center",
          gap: "12px",
          marginBottom: "12px",
          fontSize: "0.85em",
        }}
      >
        <label style={{ display: "flex", alignItems: "center", gap: "4px" }}>
          Sort:
          <select
            data-testid="sort-select"
            value={sortMode}
            onChange={(e) => setSortMode(e.target.value as CitationSortMode)}
            style={{ padding: "3px 6px" }}
          >
            {(Object.keys(SORT_LABELS) as CitationSortMode[]).map((key) => (
              <option key={key} value={key}>
                {SORT_LABELS[key]}
              </option>
            ))}
          </select>
        </label>

        <label style={{ display: "flex", alignItems: "center", gap: "4px" }}>
          <input
            type="checkbox"
            data-testid="group-toggle"
            checked={grouped}
            onChange={(e) => setGrouped(e.target.checked)}
          />
          Group by provider
        </label>

        <span style={{ color: "#666" }}>
          {citations.length} result{citations.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Render cards: grouped or flat */}
      {grouped ? (
        <GroupedView results={sorted} />
      ) : (
        <FlatView results={sorted} />
      )}
    </div>
  );
}

function FlatView({
  results,
}: {
  results: WebResearchResult[];
}): JSX.Element {
  return (
    <div role="list">
      {results.map((r, i) => (
        <div role="listitem" key={`${r.url}-${i}`}>
          <CitationCard citation={r.citation} snippet={r.snippet} />
        </div>
      ))}
    </div>
  );
}

function GroupedView({
  results,
}: {
  results: WebResearchResult[];
}): JSX.Element {
  const groups = useMemo(() => groupByProvider(results), [results]);

  return (
    <div>
      {Array.from(groups.entries()).map(([providerId, items]) => (
        <div key={providerId} className="citation-group" data-testid="citation-group">
          <h4
            className="citation-group-header"
            style={{
              margin: "16px 0 8px",
              fontSize: "0.9em",
              color: "#444",
              borderBottom: "1px solid #eee",
              paddingBottom: "4px",
            }}
          >
            {providerId} ({items.length})
          </h4>
          <div role="list">
            {items.map((r, i) => (
              <div role="listitem" key={`${r.url}-${i}`}>
                <CitationCard citation={r.citation} snippet={r.snippet} />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
