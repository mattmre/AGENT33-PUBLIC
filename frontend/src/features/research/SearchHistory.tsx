/**
 * SearchHistory: displays recent web research searches stored in React state.
 * Provides click-to-rerun functionality for past queries.
 */

/** A single search history entry. */
export interface SearchHistoryEntry {
  query: string;
  timestamp: string;
  resultCount: number;
  provider: string;
}

export interface SearchHistoryProps {
  entries: SearchHistoryEntry[];
  onRerun: (query: string) => void;
}

function formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function SearchHistory({
  entries,
  onRerun,
}: SearchHistoryProps): JSX.Element {
  if (entries.length === 0) {
    return (
      <div className="search-history" data-testid="search-history-empty">
        <p
          style={{
            color: "#888",
            fontStyle: "italic",
            fontSize: "0.85em",
            margin: "8px 0",
          }}
        >
          No recent searches.
        </p>
      </div>
    );
  }

  return (
    <div className="search-history" data-testid="search-history">
      <h4 style={{ margin: "16px 0 8px", fontSize: "0.9em", color: "#444" }}>
        Recent Searches
      </h4>
      <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
        {entries.map((entry, i) => (
          <div
            key={`${entry.query}-${entry.timestamp}-${i}`}
            className="search-history-entry"
            data-testid="search-history-entry"
            style={{
              display: "flex",
              alignItems: "center",
              gap: "10px",
              padding: "6px 10px",
              borderRadius: "4px",
              backgroundColor: "#f9f9f9",
              fontSize: "0.85em",
            }}
          >
            <span
              data-testid="history-query"
              style={{ fontWeight: 500, flex: 1, minWidth: 0 }}
            >
              {entry.query}
            </span>

            <span
              data-testid="history-provider"
              style={{
                padding: "1px 6px",
                borderRadius: "10px",
                fontSize: "0.8em",
                backgroundColor: "#e3f2fd",
                color: "#1565c0",
                whiteSpace: "nowrap",
              }}
            >
              {entry.provider}
            </span>

            <span
              data-testid="history-result-count"
              style={{ color: "#666", whiteSpace: "nowrap" }}
            >
              {entry.resultCount} result{entry.resultCount !== 1 ? "s" : ""}
            </span>

            <span
              data-testid="history-timestamp"
              style={{ color: "#999", whiteSpace: "nowrap" }}
            >
              {formatTimestamp(entry.timestamp)}
            </span>

            <button
              data-testid="rerun-search"
              onClick={() => onRerun(entry.query)}
              style={{
                padding: "2px 8px",
                fontSize: "0.85em",
                cursor: "pointer",
                border: "1px solid #1a73e8",
                borderRadius: "4px",
                backgroundColor: "transparent",
                color: "#1a73e8",
                whiteSpace: "nowrap",
              }}
            >
              Re-run
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
