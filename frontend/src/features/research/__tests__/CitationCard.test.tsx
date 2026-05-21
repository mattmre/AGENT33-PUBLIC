import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { CitationCard } from "../CitationCard";
import { CitationList } from "../CitationList";
import type { Citation, WebResearchResult } from "../CitationTypes";
import {
  compareTrustLevel,
  trustLevelLabel,
  trustLevelToDisplayTier,
} from "../CitationTypes";
import { ProviderBadge } from "../ProviderBadge";

// ---------------------------------------------------------------------------
// Factories
// ---------------------------------------------------------------------------

function buildCitation(overrides: Partial<Citation> = {}): Citation {
  return {
    title: "Understanding Async Python",
    url: "https://example.com/async-python",
    display_url: "example.com/async-python",
    domain: "example.com",
    provider_id: "searxng",
    trust_level: "fetch-verified",
    trust_reason: "Content was successfully fetched and verified",
    ...overrides,
  };
}

function buildResult(
  overrides: Partial<Omit<WebResearchResult, "citation">> & {
    citation?: Partial<Citation>;
  } = {},
): WebResearchResult {
  const { citation: citationOverrides, ...rest } = overrides;
  const citation = buildCitation(citationOverrides);
  return {
    title: citation.title,
    url: citation.url,
    snippet: "Python's asyncio module provides infrastructure for writing async code.",
    provider_id: citation.provider_id,
    rank: 1,
    domain: citation.domain,
    display_url: citation.display_url,
    trust_level: citation.trust_level,
    trust_reason: citation.trust_reason,
    citation,
    ...rest,
  };
}

// ---------------------------------------------------------------------------
// CitationTypes utility tests
// ---------------------------------------------------------------------------

describe("CitationTypes utilities", () => {
  it("maps fetch-verified to high display tier", () => {
    expect(trustLevelToDisplayTier("fetch-verified")).toBe("high");
  });

  it("maps search-indexed to medium display tier", () => {
    expect(trustLevelToDisplayTier("search-indexed")).toBe("medium");
  });

  it("maps blocked to low display tier", () => {
    expect(trustLevelToDisplayTier("blocked")).toBe("low");
  });

  it("returns human-readable trust labels", () => {
    expect(trustLevelLabel("fetch-verified")).toBe("Verified");
    expect(trustLevelLabel("search-indexed")).toBe("Indexed");
    expect(trustLevelLabel("blocked")).toBe("Blocked");
  });

  it("sorts trust levels with highest trust first", () => {
    expect(compareTrustLevel("fetch-verified", "search-indexed")).toBeLessThan(0);
    expect(compareTrustLevel("search-indexed", "blocked")).toBeLessThan(0);
    expect(compareTrustLevel("blocked", "fetch-verified")).toBeGreaterThan(0);
    expect(compareTrustLevel("fetch-verified", "fetch-verified")).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// ProviderBadge
// ---------------------------------------------------------------------------

describe("ProviderBadge", () => {
  it("renders known provider with display name", () => {
    render(<ProviderBadge providerId="searxng" />);
    const badge = screen.getByTestId("provider-badge");
    expect(badge).toHaveTextContent("SearXNG");
    expect(badge).toHaveAttribute("data-provider", "searxng");
  });

  it("renders Google provider with correct styling", () => {
    render(<ProviderBadge providerId="google" />);
    const badge = screen.getByTestId("provider-badge");
    expect(badge).toHaveTextContent("Google");
    expect(badge).toHaveStyle({ backgroundColor: "#4285f4" });
  });

  it("falls back to raw provider_id for unknown providers", () => {
    render(<ProviderBadge providerId="custom-search" />);
    const badge = screen.getByTestId("provider-badge");
    expect(badge).toHaveTextContent("custom-search");
  });

  it("is case-insensitive for provider lookup", () => {
    render(<ProviderBadge providerId="SearXNG" />);
    expect(screen.getByTestId("provider-badge")).toHaveTextContent("SearXNG");
  });
});

// ---------------------------------------------------------------------------
// CitationCard
// ---------------------------------------------------------------------------

describe("CitationCard", () => {
  it("renders citation title as a link to the URL", () => {
    const citation = buildCitation({
      title: "FastAPI Documentation",
      url: "https://fastapi.tiangolo.com",
    });
    render(<CitationCard citation={citation} />);

    const link = screen.getByRole("link", { name: "FastAPI Documentation" });
    expect(link).toHaveAttribute("href", "https://fastapi.tiangolo.com");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("displays the display_url text", () => {
    const citation = buildCitation({ display_url: "fastapi.tiangolo.com/tutorial" });
    render(<CitationCard citation={citation} />);
    expect(screen.getByText("fastapi.tiangolo.com/tutorial")).toBeInTheDocument();
  });

  it("shows the provider badge", () => {
    const citation = buildCitation({ provider_id: "bing" });
    render(<CitationCard citation={citation} />);
    expect(screen.getByTestId("provider-badge")).toHaveTextContent("Bing");
  });

  it("displays green trust indicator for fetch-verified", () => {
    const citation = buildCitation({ trust_level: "fetch-verified" });
    render(<CitationCard citation={citation} />);

    const indicator = screen.getByTestId("trust-indicator");
    expect(indicator).toHaveTextContent("Verified");
  });

  it("displays yellow trust indicator for search-indexed", () => {
    const citation = buildCitation({ trust_level: "search-indexed" });
    render(<CitationCard citation={citation} />);

    const indicator = screen.getByTestId("trust-indicator");
    expect(indicator).toHaveTextContent("Indexed");
  });

  it("displays red trust indicator for blocked", () => {
    const citation = buildCitation({ trust_level: "blocked" });
    render(<CitationCard citation={citation} />);

    const indicator = screen.getByTestId("trust-indicator");
    expect(indicator).toHaveTextContent("Blocked");
  });

  it("shows snippet text when provided", () => {
    const citation = buildCitation();
    render(
      <CitationCard citation={citation} snippet="This is a relevant snippet." />,
    );
    expect(screen.getByText("This is a relevant snippet.")).toBeInTheDocument();
  });

  it("does not render snippet section when snippet is absent", () => {
    const citation = buildCitation();
    render(<CitationCard citation={citation} />);
    expect(screen.queryByText(/snippet/i)).not.toBeInTheDocument();
  });

  it("shows published date when provided", () => {
    const citation = buildCitation();
    render(
      <CitationCard citation={citation} publishedAt="2026-01-15T10:30:00Z" />,
    );
    expect(screen.getByText("Jan 15, 2026")).toBeInTheDocument();
  });

  it("handles missing optional publishedAt field", () => {
    const citation = buildCitation();
    const { container } = render(<CitationCard citation={citation} />);
    expect(container.querySelector(".citation-date")).not.toBeInTheDocument();
  });

  it("shows domain name", () => {
    const citation = buildCitation({ domain: "docs.python.org" });
    render(<CitationCard citation={citation} />);
    expect(screen.getByText("docs.python.org")).toBeInTheDocument();
  });

  it("toggles expandable preview on click", async () => {
    const user = userEvent.setup();
    const citation = buildCitation({
      trust_reason: "Fetched with 200 OK in 142ms",
    });
    render(<CitationCard citation={citation} />);

    // Preview should be hidden initially
    expect(screen.queryByTestId("citation-preview")).not.toBeInTheDocument();

    // Click to expand
    await user.click(screen.getByTestId("expand-toggle"));
    expect(screen.getByTestId("citation-preview")).toBeInTheDocument();
    expect(screen.getByText("Fetched with 200 OK in 142ms")).toBeInTheDocument();
    expect(screen.getByTestId("expand-toggle")).toHaveTextContent("Hide details");

    // Click to collapse
    await user.click(screen.getByTestId("expand-toggle"));
    expect(screen.queryByTestId("citation-preview")).not.toBeInTheDocument();
    expect(screen.getByTestId("expand-toggle")).toHaveTextContent("Show details");
  });

  it("renders the left border color matching the trust tier", () => {
    const citation = buildCitation({ trust_level: "blocked" });
    render(<CitationCard citation={citation} />);

    const card = screen.getByTestId("citation-card");
    // Red border for "blocked" trust level
    expect(card).toHaveStyle({ borderLeft: "4px solid #f44336" });
  });
});

// ---------------------------------------------------------------------------
// CitationList
// ---------------------------------------------------------------------------

describe("CitationList", () => {
  it("shows empty state when no citations are provided", () => {
    render(<CitationList citations={[]} />);
    expect(screen.getByTestId("citation-list-empty")).toBeInTheDocument();
    expect(screen.getByText("No citations available.")).toBeInTheDocument();
  });

  it("renders multiple citation cards", () => {
    const results = [
      buildResult({ citation: { title: "Result One" } }),
      buildResult({ citation: { title: "Result Two" }, rank: 2 }),
      buildResult({ citation: { title: "Result Three" }, rank: 3 }),
    ];

    render(<CitationList citations={results} />);

    expect(screen.getByTestId("citation-list")).toBeInTheDocument();
    const cards = screen.getAllByTestId("citation-card");
    expect(cards).toHaveLength(3);
    expect(screen.getByText("3 results")).toBeInTheDocument();
  });

  it("renders singular count for one result", () => {
    render(<CitationList citations={[buildResult()]} />);
    expect(screen.getByText("1 result")).toBeInTheDocument();
  });

  it("sorts by trust level when sort control is changed", async () => {
    const user = userEvent.setup();
    const results = [
      buildResult({
        rank: 1,
        citation: { title: "Blocked Source", trust_level: "blocked" },
        trust_level: "blocked",
      }),
      buildResult({
        rank: 2,
        citation: { title: "Verified Source", trust_level: "fetch-verified" },
        trust_level: "fetch-verified",
      }),
      buildResult({
        rank: 3,
        citation: { title: "Indexed Source", trust_level: "search-indexed" },
        trust_level: "search-indexed",
      }),
    ];

    render(<CitationList citations={results} />);

    // Default sort is relevance (by rank), so "Blocked Source" appears first
    const cardsBefore = screen.getAllByTestId("citation-card");
    expect(
      within(cardsBefore[0]).getByRole("link", { name: "Blocked Source" }),
    ).toBeInTheDocument();

    // Change to trust sort
    await user.selectOptions(screen.getByTestId("sort-select"), "trust");

    // After trust sort, "Verified Source" (fetch-verified) should be first
    const cardsAfter = screen.getAllByTestId("citation-card");
    expect(
      within(cardsAfter[0]).getByRole("link", { name: "Verified Source" }),
    ).toBeInTheDocument();
    expect(
      within(cardsAfter[1]).getByRole("link", { name: "Indexed Source" }),
    ).toBeInTheDocument();
    expect(
      within(cardsAfter[2]).getByRole("link", { name: "Blocked Source" }),
    ).toBeInTheDocument();
  });

  it("groups results by provider when group toggle is checked", async () => {
    const user = userEvent.setup();
    const results = [
      buildResult({ provider_id: "searxng", citation: { provider_id: "searxng" } }),
      buildResult({ provider_id: "google", citation: { provider_id: "google" } }),
      buildResult({ provider_id: "searxng", citation: { provider_id: "searxng" }, rank: 2 }),
    ];

    render(<CitationList citations={results} />);

    // Initially flat (no groups)
    expect(screen.queryByTestId("citation-group")).not.toBeInTheDocument();

    // Enable grouping
    await user.click(screen.getByTestId("group-toggle"));

    const groups = screen.getAllByTestId("citation-group");
    expect(groups).toHaveLength(2);

    // First group (searxng) should have 2 items, second (google) should have 1
    const firstGroupCards = within(groups[0]).getAllByTestId("citation-card");
    expect(firstGroupCards).toHaveLength(2);

    const secondGroupCards = within(groups[1]).getAllByTestId("citation-card");
    expect(secondGroupCards).toHaveLength(1);
  });

  it("respects initial sortBy prop", () => {
    const results = [
      buildResult({
        rank: 1,
        citation: { title: "Blocked", trust_level: "blocked" },
        trust_level: "blocked",
      }),
      buildResult({
        rank: 2,
        citation: { title: "Verified", trust_level: "fetch-verified" },
        trust_level: "fetch-verified",
      }),
    ];

    // Pass sortBy="trust" as initial
    render(<CitationList citations={results} sortBy="trust" />);

    const select = screen.getByTestId("sort-select") as HTMLSelectElement;
    expect(select.value).toBe("trust");

    // Verified should be first with trust sort
    const cards = screen.getAllByTestId("citation-card");
    expect(
      within(cards[0]).getByRole("link", { name: "Verified" }),
    ).toBeInTheDocument();
  });

  it("respects initial groupByProvider prop", () => {
    const results = [
      buildResult({ provider_id: "google", citation: { provider_id: "google" } }),
      buildResult({ provider_id: "bing", citation: { provider_id: "bing" } }),
    ];

    render(<CitationList citations={results} groupByProvider />);

    // Should start grouped
    const groups = screen.getAllByTestId("citation-group");
    expect(groups).toHaveLength(2);
  });

  it("passes snippet from result to citation card", () => {
    const results = [
      buildResult({ snippet: "Important research finding about neural nets." }),
    ];

    render(<CitationList citations={results} />);
    expect(
      screen.getByText("Important research finding about neural nets."),
    ).toBeInTheDocument();
  });
});
