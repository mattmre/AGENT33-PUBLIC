import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { IngestionReviewPanel } from "./IngestionReviewPanel";

function mockFetchResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

describe("IngestionReviewPanel", () => {
  beforeEach(() => {
    (window as any).__AGENT33_CONFIG__ = {
      API_BASE_URL: "http://localhost:8000"
    };
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the review queue and asset history timeline", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/v1/ingestion/review-queue")) {
        return Promise.resolve(
          mockFetchResponse([
            {
              id: "asset-1",
              name: "history-pack",
              asset_type: "pack",
              status: "candidate",
              confidence: "low",
              source_uri: "https://example.test/history-pack",
              tenant_id: "tenant-1",
              created_at: "2026-04-25T10:00:00Z",
              updated_at: "2026-04-25T10:00:00Z",
              validated_at: null,
              published_at: null,
              revoked_at: null,
              revocation_reason: null,
              metadata: {
                review_required: true,
                quarantine: true
              }
            }
          ])
        );
      }

      if (url.includes("/v1/ingestion/candidates/asset-1/history")) {
        return Promise.resolve(
          mockFetchResponse({
            asset: {
              id: "asset-1",
              name: "history-pack",
              asset_type: "pack",
              status: "candidate",
              confidence: "low",
              source_uri: "https://example.test/history-pack",
              tenant_id: "tenant-1",
              created_at: "2026-04-25T10:00:00Z",
              updated_at: "2026-04-25T10:05:00Z",
              validated_at: null,
              published_at: null,
              revoked_at: null,
              revocation_reason: null,
              metadata: {
                review_required: true,
                quarantine: true
              }
            },
            history: [
              {
                asset_id: "asset-1",
                tenant_id: "tenant-1",
                from_status: "candidate",
                to_status: "candidate",
                event_type: "ingested",
                operator: "system",
                reason: "Asset entered the ingestion lifecycle.",
                details: {},
                occurred_at: "2026-04-25T10:00:00Z"
              },
              {
                asset_id: "asset-1",
                tenant_id: "tenant-1",
                from_status: "candidate",
                to_status: "candidate",
                event_type: "review_required",
                operator: "intake_pipeline",
                reason: "Asset requires operator review before promotion.",
                details: {
                  review_required: true
                },
                occurred_at: "2026-04-25T10:01:00Z"
              },
              {
                asset_id: "asset-1",
                tenant_id: "tenant-1",
                from_status: "candidate",
                to_status: "candidate",
                event_type: "quarantined",
                operator: "intake_pipeline",
                reason: "Asset was quarantined for manual inspection.",
                details: {
                  quarantine: true
                },
                occurred_at: "2026-04-25T10:02:00Z"
              }
            ]
          })
        );
      }

      return Promise.reject(new Error(`Unhandled request: ${url}`));
    });

    vi.stubGlobal("fetch", fetchMock);

    render(<IngestionReviewPanel token="token" apiKey="" onResult={vi.fn()} />);

    expect(await screen.findByRole("button", { name: /history-pack/i })).toBeInTheDocument();
    expect(await screen.findByText("Marked for review")).toBeInTheDocument();
    expect(screen.getByText("Quarantined")).toBeInTheDocument();
    expect(screen.getAllByText("Review required").length).toBeGreaterThan(0);
  });

  it("filters review assets by confidence, quarantine, and text", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/v1/ingestion/review-queue")) {
        return Promise.resolve(
          mockFetchResponse([
            {
              id: "asset-1",
              name: "safe-pack",
              asset_type: "pack",
              status: "candidate",
              confidence: "medium",
              source_uri: "https://example.test/safe-pack",
              tenant_id: "tenant-1",
              created_at: "2026-04-25T10:00:00Z",
              updated_at: "2026-04-25T10:00:00Z",
              validated_at: null,
              published_at: null,
              revoked_at: null,
              revocation_reason: null,
              metadata: {
                review_required: true
              }
            },
            {
              id: "asset-2",
              name: "risky-pack",
              asset_type: "pack",
              status: "candidate",
              confidence: "low",
              source_uri: "https://example.test/risky-pack",
              tenant_id: "tenant-1",
              created_at: "2026-04-25T10:01:00Z",
              updated_at: "2026-04-25T10:01:00Z",
              validated_at: null,
              published_at: null,
              revoked_at: null,
              revocation_reason: null,
              metadata: {
                review_required: true,
                quarantine: true
              }
            }
          ])
        );
      }

      if (url.includes("/v1/ingestion/candidates/asset-1/history")) {
        return Promise.resolve(
          mockFetchResponse({
            asset: {
              id: "asset-1",
              name: "safe-pack",
              asset_type: "pack",
              status: "candidate",
              confidence: "medium",
              source_uri: "https://example.test/safe-pack",
              tenant_id: "tenant-1",
              created_at: "2026-04-25T10:00:00Z",
              updated_at: "2026-04-25T10:00:00Z",
              validated_at: null,
              published_at: null,
              revoked_at: null,
              revocation_reason: null,
              metadata: {
                review_required: true
              }
            },
            history: []
          })
        );
      }

      return Promise.reject(new Error(`Unhandled request: ${url}`));
    });

    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<IngestionReviewPanel token="token" apiKey="" onResult={vi.fn()} />);

    expect(await screen.findByRole("button", { name: /safe-pack/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /risky-pack/i })).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Attention"), "quarantine");

    expect(screen.queryByRole("button", { name: /safe-pack/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /risky-pack/i })).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Confidence"), "medium");

    expect(screen.getByText("No assets match the current filters.")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Attention"), "all");
    await user.clear(screen.getByLabelText("Search assets"));
    await user.type(screen.getByLabelText("Search assets"), "safe");

    expect(screen.getByRole("button", { name: /safe-pack/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /risky-pack/i })).not.toBeInTheDocument();
  });

  it("submits approve actions and refreshes the selected asset", async () => {
    let assetStatus = "candidate";
    const baseAsset = {
      id: "asset-1",
      name: "approve-pack",
      asset_type: "pack",
      status: "candidate",
      confidence: "medium",
      source_uri: "https://example.test/approve-pack",
      tenant_id: "tenant-1",
      created_at: "2026-04-25T10:00:00Z",
      updated_at: "2026-04-25T10:00:00Z",
      validated_at: null,
      published_at: null,
      revoked_at: null,
      revocation_reason: null,
      metadata: {
        review_required: true
      }
    };
    let queueItems = [
      baseAsset
    ];

    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.includes("/v1/ingestion/review-queue") && method === "GET") {
        return Promise.resolve(mockFetchResponse(queueItems));
      }

      if (url.includes("/v1/ingestion/candidates/asset-1/history")) {
        return Promise.resolve(
          mockFetchResponse({
            asset: {
              ...baseAsset,
              status: assetStatus,
              updated_at: "2026-04-25T10:06:00Z",
              validated_at: assetStatus === "validated" ? "2026-04-25T10:06:00Z" : null,
              metadata: {
                review_required: assetStatus === "candidate"
              }
            },
            history: [
              {
                asset_id: "asset-1",
                tenant_id: "tenant-1",
                from_status: "candidate",
                to_status: assetStatus,
                event_type: assetStatus === "validated" ? "approved" : "review_required",
                operator: "operations-hub",
                reason:
                  assetStatus === "validated"
                    ? "Approved in UI"
                    : "Asset requires operator review before promotion.",
                details: {},
                occurred_at: "2026-04-25T10:06:00Z"
              }
            ]
          })
        );
      }

      if (url.includes("/v1/ingestion/review-queue/asset-1/approve") && method === "POST") {
        assetStatus = "validated";
        queueItems = [];
        return Promise.resolve(
          mockFetchResponse({
            ...baseAsset,
            status: "validated",
            updated_at: "2026-04-25T10:06:00Z",
            validated_at: "2026-04-25T10:06:00Z",
            metadata: {
              review_required: false
            }
          })
        );
      }

      return Promise.reject(new Error(`Unhandled request: ${method} ${url}`));
    });

    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<IngestionReviewPanel token="token" apiKey="" onResult={vi.fn()} />);

    expect(await screen.findByLabelText("Operator")).toHaveValue("operations-hub");
    await user.type(await screen.findByLabelText("Review notes"), "Approved in UI");
    await user.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => {
      expect(screen.getByText("approve-pack approved and moved to validated.")).toBeInTheDocument();
    });
    expect(screen.getByText("No assets currently require review.")).toBeInTheDocument();
    expect(screen.getAllByText("Validated").length).toBeGreaterThan(0);
  });

  it("switches to the next queued asset without reloading stale history", async () => {
    let asset1HistoryCalls = 0;
    let asset1Status = "candidate";
    let queueItems = [
      {
        id: "asset-1",
        name: "first-pack",
        asset_type: "pack",
        status: "candidate",
        confidence: "medium",
        source_uri: "https://example.test/first-pack",
        tenant_id: "tenant-1",
        created_at: "2026-04-25T10:00:00Z",
        updated_at: "2026-04-25T10:00:00Z",
        validated_at: null,
        published_at: null,
        revoked_at: null,
        revocation_reason: null,
        metadata: { review_required: true }
      },
      {
        id: "asset-2",
        name: "second-pack",
        asset_type: "pack",
        status: "candidate",
        confidence: "low",
        source_uri: "https://example.test/second-pack",
        tenant_id: "tenant-1",
        created_at: "2026-04-25T10:01:00Z",
        updated_at: "2026-04-25T10:01:00Z",
        validated_at: null,
        published_at: null,
        revoked_at: null,
        revocation_reason: null,
        metadata: { review_required: true, quarantine: true }
      }
    ];

    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.includes("/v1/ingestion/review-queue") && method === "GET") {
        return Promise.resolve(mockFetchResponse(queueItems));
      }

      if (url.includes("/v1/ingestion/candidates/asset-1/history")) {
        asset1HistoryCalls += 1;
        return Promise.resolve(
          mockFetchResponse({
            asset: {
              ...queueItems[0],
              status: asset1Status,
              validated_at: asset1Status === "validated" ? "2026-04-25T10:05:00Z" : null,
              metadata: { review_required: asset1Status === "candidate" }
            },
            history: [
              {
                asset_id: "asset-1",
                tenant_id: "tenant-1",
                from_status: "candidate",
                to_status: asset1Status,
                event_type: asset1Status === "validated" ? "approved" : "review_required",
                operator: "operations-hub",
                reason:
                  asset1Status === "validated"
                    ? "Approved in UI"
                    : "Asset requires operator review before promotion.",
                details: {},
                occurred_at: "2026-04-25T10:05:00Z"
              }
            ]
          })
        );
      }

      if (url.includes("/v1/ingestion/candidates/asset-2/history")) {
        return Promise.resolve(
          mockFetchResponse({
            asset: queueItems[queueItems.length - 1],
            history: [
              {
                asset_id: "asset-2",
                tenant_id: "tenant-1",
                from_status: "candidate",
                to_status: "candidate",
                event_type: "quarantined",
                operator: "intake_pipeline",
                reason: "Awaiting operator inspection.",
                details: { quarantine: true },
                occurred_at: "2026-04-25T10:02:00Z"
              }
            ]
          })
        );
      }

      if (url.includes("/v1/ingestion/review-queue/asset-1/approve") && method === "POST") {
        asset1Status = "validated";
        queueItems = [queueItems[1]];
        return Promise.resolve(
          mockFetchResponse({
            id: "asset-1",
            name: "first-pack",
            asset_type: "pack",
            status: "validated",
            confidence: "medium",
            source_uri: "https://example.test/first-pack",
            tenant_id: "tenant-1",
            created_at: "2026-04-25T10:00:00Z",
            updated_at: "2026-04-25T10:05:00Z",
            validated_at: "2026-04-25T10:05:00Z",
            published_at: null,
            revoked_at: null,
            revocation_reason: null,
            metadata: { review_required: false }
          })
        );
      }

      return Promise.reject(new Error(`Unhandled request: ${method} ${url}`));
    });

    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<IngestionReviewPanel token="token" apiKey="" onResult={vi.fn()} />);

    expect(await screen.findByRole("button", { name: /first-pack/i })).toBeInTheDocument();
    await user.type(await screen.findByLabelText("Review notes"), "Approved in UI");
    await user.click(screen.getByRole("button", { name: "Approve" }));

    expect(await screen.findByRole("button", { name: /second-pack/i })).toBeInTheDocument();
    expect(await screen.findByText("Awaiting operator inspection.")).toBeInTheDocument();
    expect(asset1HistoryCalls).toBe(1);
  });
});
