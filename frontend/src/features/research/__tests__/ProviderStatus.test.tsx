import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProviderStatus } from "../ProviderStatus";
import type { ProviderStatusEntry } from "../ProviderStatus";

// ---------------------------------------------------------------------------
// Factories
// ---------------------------------------------------------------------------

function buildProvider(
  overrides: Partial<ProviderStatusEntry> = {},
): ProviderStatusEntry {
  return {
    name: "SearXNG",
    enabled: true,
    status: "ok",
    last_check: null,
    total_calls: 0,
    success_rate: 1.0,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Mock setup
// ---------------------------------------------------------------------------

const mockFetch = vi.fn();

beforeEach(() => {
  mockFetch.mockReset();
  window.__AGENT33_CONFIG__ = { API_BASE_URL: "http://test-api" };
  vi.stubGlobal("fetch", mockFetch);
});

afterEach(() => {
  vi.restoreAllMocks();
});

function setupFetchResponse(providers: ProviderStatusEntry[]) {
  mockFetch.mockResolvedValueOnce({
    ok: true,
    json: () => Promise.resolve(providers),
  });
}

function setupFetchError(detail: string, status = 500) {
  mockFetch.mockResolvedValueOnce({
    ok: false,
    statusText: `Error ${status}`,
    json: () => Promise.resolve({ detail }),
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ProviderStatus", () => {
  it("renders provider cards after fetching status", async () => {
    const providers = [
      buildProvider({ name: "SearXNG" }),
      buildProvider({ name: "Governed HTTP Fetch", status: "ok" }),
    ];
    setupFetchResponse(providers);

    render(<ProviderStatus token="test-token" />);

    await waitFor(() => {
      const cards = screen.getAllByTestId("provider-status-card");
      expect(cards).toHaveLength(2);
    });

    expect(screen.getByText("SearXNG")).toBeInTheDocument();
    expect(screen.getByText("Governed HTTP Fetch")).toBeInTheDocument();
  });

  it("calls the correct API endpoint with auth header", async () => {
    setupFetchResponse([buildProvider()]);

    render(<ProviderStatus token="my-jwt-token" />);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        "http://test-api/v1/research/providers/status",
        { headers: { Authorization: "Bearer my-jwt-token" } },
      );
    });
  });

  it("shows connected badge for enabled providers", async () => {
    setupFetchResponse([buildProvider({ enabled: true })]);

    render(<ProviderStatus token="test-token" />);

    await waitFor(() => {
      expect(screen.getByTestId("enabled-badge")).toHaveTextContent(
        "Connected",
      );
    });
  });

  it("shows disconnected badge for disabled providers", async () => {
    setupFetchResponse([
      buildProvider({ name: "Disabled", enabled: false, status: "unconfigured" }),
    ]);

    render(<ProviderStatus token="test-token" />);

    await waitFor(() => {
      expect(screen.getByTestId("enabled-badge")).toHaveTextContent(
        "Disconnected",
      );
    });
  });

  it("displays status indicator with correct color for ok status", async () => {
    setupFetchResponse([buildProvider({ status: "ok" })]);

    render(<ProviderStatus token="test-token" />);

    await waitFor(() => {
      const indicator = screen.getByTestId("status-indicator");
      expect(indicator).toHaveStyle({ backgroundColor: "#4caf50" });
    });
  });

  it("displays status indicator with warning color for unconfigured", async () => {
    setupFetchResponse([
      buildProvider({ status: "unconfigured", enabled: false }),
    ]);

    render(<ProviderStatus token="test-token" />);

    await waitFor(() => {
      const indicator = screen.getByTestId("status-indicator");
      expect(indicator).toHaveStyle({ backgroundColor: "#ff9800" });
    });
  });

  it("displays call count and success rate", async () => {
    setupFetchResponse([
      buildProvider({ total_calls: 42, success_rate: 0.95 }),
    ]);

    render(<ProviderStatus token="test-token" />);

    await waitFor(() => {
      expect(screen.getByTestId("call-count")).toHaveTextContent("42 calls");
      expect(screen.getByTestId("success-rate")).toHaveTextContent(
        "95% success",
      );
    });
  });

  it("displays last check timestamp when available", async () => {
    setupFetchResponse([
      buildProvider({ last_check: "2026-03-15T12:00:00Z" }),
    ]);

    render(<ProviderStatus token="test-token" />);

    await waitFor(() => {
      const lastCheck = screen.getByTestId("last-check");
      // Should show formatted timestamp, not "Never"
      expect(lastCheck).not.toHaveTextContent("Never");
    });
  });

  it("displays 'Never' when last_check is null", async () => {
    setupFetchResponse([buildProvider({ last_check: null })]);

    render(<ProviderStatus token="test-token" />);

    await waitFor(() => {
      expect(screen.getByTestId("last-check")).toHaveTextContent("Never");
    });
  });

  it("shows error message on fetch failure", async () => {
    setupFetchError("Service unavailable");

    render(<ProviderStatus token="test-token" />);

    await waitFor(() => {
      expect(screen.getByTestId("provider-status-error")).toHaveTextContent(
        "Service unavailable",
      );
    });
  });

  it("does not fetch when token is null", () => {
    render(<ProviderStatus token={null} />);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("refreshes on button click", async () => {
    const user = userEvent.setup();
    const firstBatch = [buildProvider({ name: "First" })];
    const secondBatch = [
      buildProvider({ name: "First" }),
      buildProvider({ name: "Second" }),
    ];
    setupFetchResponse(firstBatch);

    render(<ProviderStatus token="test-token" />);

    await waitFor(() => {
      expect(screen.getAllByTestId("provider-status-card")).toHaveLength(1);
    });

    setupFetchResponse(secondBatch);
    await user.click(screen.getByTestId("refresh-status"));

    await waitFor(() => {
      expect(screen.getAllByTestId("provider-status-card")).toHaveLength(2);
    });
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it("shows empty state when no providers are configured", async () => {
    setupFetchResponse([]);

    render(<ProviderStatus token="test-token" />);

    await waitFor(() => {
      expect(
        screen.getByText("No providers configured."),
      ).toBeInTheDocument();
    });
  });
});
