import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SearchHistory } from "../SearchHistory";
import type { SearchHistoryEntry } from "../SearchHistory";

// ---------------------------------------------------------------------------
// Factories
// ---------------------------------------------------------------------------

function buildEntry(
  overrides: Partial<SearchHistoryEntry> = {},
): SearchHistoryEntry {
  return {
    query: "FastAPI dependency injection",
    timestamp: "2026-03-15T14:30:00Z",
    resultCount: 5,
    provider: "searxng",
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("SearchHistory", () => {
  it("shows empty state when no entries exist", () => {
    const onRerun = vi.fn();
    render(<SearchHistory entries={[]} onRerun={onRerun} />);

    expect(screen.getByTestId("search-history-empty")).toBeInTheDocument();
    expect(screen.getByText("No recent searches.")).toBeInTheDocument();
  });

  it("renders entries with query text", () => {
    const entries = [
      buildEntry({ query: "Python asyncio patterns" }),
      buildEntry({ query: "React hooks best practices" }),
    ];
    const onRerun = vi.fn();

    render(<SearchHistory entries={entries} onRerun={onRerun} />);

    expect(screen.getByTestId("search-history")).toBeInTheDocument();
    const historyEntries = screen.getAllByTestId("search-history-entry");
    expect(historyEntries).toHaveLength(2);
    expect(screen.getByText("Python asyncio patterns")).toBeInTheDocument();
    expect(
      screen.getByText("React hooks best practices"),
    ).toBeInTheDocument();
  });

  it("displays the provider name for each entry", () => {
    const entries = [buildEntry({ provider: "google" })];
    const onRerun = vi.fn();

    render(<SearchHistory entries={entries} onRerun={onRerun} />);

    expect(screen.getByTestId("history-provider")).toHaveTextContent("google");
  });

  it("displays result count with correct pluralization", () => {
    const entries = [
      buildEntry({ resultCount: 1, query: "single" }),
      buildEntry({ resultCount: 5, query: "multiple" }),
    ];
    const onRerun = vi.fn();

    render(<SearchHistory entries={entries} onRerun={onRerun} />);

    const counts = screen.getAllByTestId("history-result-count");
    expect(counts[0]).toHaveTextContent("1 result");
    expect(counts[1]).toHaveTextContent("5 results");
  });

  it("displays formatted timestamp", () => {
    const entries = [buildEntry({ timestamp: "2026-03-15T14:30:00Z" })];
    const onRerun = vi.fn();

    render(<SearchHistory entries={entries} onRerun={onRerun} />);

    const ts = screen.getByTestId("history-timestamp");
    // Should be formatted, not raw ISO
    expect(ts.textContent).not.toBe("2026-03-15T14:30:00Z");
    expect(ts.textContent).toBeTruthy();
  });

  it("calls onRerun with the query when Re-run button is clicked", async () => {
    const user = userEvent.setup();
    const onRerun = vi.fn();
    const entries = [buildEntry({ query: "rerun this query" })];

    render(<SearchHistory entries={entries} onRerun={onRerun} />);

    await user.click(screen.getByTestId("rerun-search"));

    expect(onRerun).toHaveBeenCalledTimes(1);
    expect(onRerun).toHaveBeenCalledWith("rerun this query");
  });

  it("renders Re-run button for each entry", () => {
    const entries = [
      buildEntry({ query: "first" }),
      buildEntry({ query: "second" }),
      buildEntry({ query: "third" }),
    ];
    const onRerun = vi.fn();

    render(<SearchHistory entries={entries} onRerun={onRerun} />);

    const buttons = screen.getAllByTestId("rerun-search");
    expect(buttons).toHaveLength(3);
    buttons.forEach((btn) => {
      expect(btn).toHaveTextContent("Re-run");
    });
  });

  it("calls onRerun with the correct query for the clicked entry", async () => {
    const user = userEvent.setup();
    const onRerun = vi.fn();
    const entries = [
      buildEntry({ query: "query-a" }),
      buildEntry({ query: "query-b" }),
    ];

    render(<SearchHistory entries={entries} onRerun={onRerun} />);

    const buttons = screen.getAllByTestId("rerun-search");
    await user.click(buttons[1]);

    expect(onRerun).toHaveBeenCalledWith("query-b");
  });

  it("shows the heading when entries exist", () => {
    const entries = [buildEntry()];
    const onRerun = vi.fn();

    render(<SearchHistory entries={entries} onRerun={onRerun} />);

    expect(screen.getByText("Recent Searches")).toBeInTheDocument();
  });

  it("does not show heading when entries are empty", () => {
    const onRerun = vi.fn();

    render(<SearchHistory entries={[]} onRerun={onRerun} />);

    expect(screen.queryByText("Recent Searches")).not.toBeInTheDocument();
  });
});
