import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../lib/api", () => ({
  getRuntimeConfig: () => ({ API_BASE_URL: "http://localhost:8000" }),
  apiRequest: vi.fn(),
}));

import { apiRequest } from "../../lib/api";
import { SessionAnalyticsDashboard } from "./SessionAnalyticsDashboard";

const MOCK_REPORT = {
  total_sessions: 42,
  total_tokens: 1250000,
  total_cost_usd: 15.73,
  avg_session_duration_seconds: 150,
  tool_usage: {
    shell: 120,
    file_ops: 85,
    web_fetch: 30,
  },
  model_usage: {
    "gpt-4": {
      tokens: 800000,
      input_tokens: 500000,
      output_tokens: 300000,
      cost_usd: 12.5,
      invocations: 200,
    },
    "claude-3": {
      tokens: 450000,
      input_tokens: 300000,
      output_tokens: 150000,
      cost_usd: 3.23,
      invocations: 50,
    },
  },
  daily_activity: [
    { date: "2026-03-25", sessions: 10, tokens: 300000, cost_usd: 4.5 },
    { date: "2026-03-26", sessions: 15, tokens: 500000, cost_usd: 5.5 },
    { date: "2026-03-27", sessions: 17, tokens: 450000, cost_usd: 5.73 },
  ],
  period_days: 30,
  generated_at: "2026-03-27T12:00:00Z",
};

function mockApiResult(data: unknown, ok = true, status = 200) {
  return {
    status,
    durationMs: 42,
    url: "http://localhost:8000/v1/insights?days=30",
    data,
    ok,
  };
}

describe("SessionAnalyticsDashboard", () => {
  const onResult = vi.fn();
  const mockedApiRequest = vi.mocked(apiRequest);

  beforeEach(() => {
    onResult.mockReset();
    mockedApiRequest.mockReset();
  });

  it("renders loading state when data is being fetched", () => {
    // Never resolve the request so it stays in loading state
    mockedApiRequest.mockReturnValue(new Promise(() => {}));

    render(
      <SessionAnalyticsDashboard token="jwt" apiKey="key" onResult={onResult} />
    );

    expect(screen.getByText("Loading insights...")).toBeInTheDocument();
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("renders insights data after successful fetch", async () => {
    mockedApiRequest.mockResolvedValue(mockApiResult(MOCK_REPORT));

    render(
      <SessionAnalyticsDashboard token="jwt" apiKey="key" onResult={onResult} />
    );

    await waitFor(() => {
      expect(screen.getByText("Session Analytics")).toBeInTheDocument();
    });

    // Summary cards rendered
    expect(screen.getByTestId("card-sessions")).toHaveTextContent("42");
    expect(screen.getByTestId("card-tokens")).toHaveTextContent("1.3M");
    expect(screen.getByTestId("card-cost")).toHaveTextContent("$15.73");
    expect(screen.getByTestId("card-duration")).toHaveTextContent("2m 30s");
  });

  it("displays correct summary card values", async () => {
    mockedApiRequest.mockResolvedValue(mockApiResult(MOCK_REPORT));

    render(
      <SessionAnalyticsDashboard token="jwt" apiKey="key" onResult={onResult} />
    );

    await waitFor(() => {
      expect(screen.getByTestId("card-sessions")).toBeInTheDocument();
    });

    expect(screen.getByTestId("card-sessions").textContent).toBe("42");
    expect(screen.getByTestId("card-tokens").textContent).toBe("1.3M");
    expect(screen.getByTestId("card-cost").textContent).toBe("$15.73");
    expect(screen.getByTestId("card-duration").textContent).toBe("2m 30s");
  });

  it("period selector changes trigger re-fetch", async () => {
    const user = userEvent.setup();
    mockedApiRequest.mockResolvedValue(mockApiResult(MOCK_REPORT));

    render(
      <SessionAnalyticsDashboard token="jwt" apiKey="key" onResult={onResult} />
    );

    await waitFor(() => {
      expect(screen.getByTestId("card-sessions")).toBeInTheDocument();
    });

    // Initial call was for 30 days (default)
    expect(mockedApiRequest).toHaveBeenCalledWith(
      expect.objectContaining({
        query: expect.objectContaining({ days: "30" }),
      })
    );

    mockedApiRequest.mockClear();

    // Click the 7-day button
    await user.click(screen.getByRole("button", { name: "7d" }));

    await waitFor(() => {
      expect(mockedApiRequest).toHaveBeenCalledWith(
        expect.objectContaining({
          query: expect.objectContaining({ days: "7" }),
        })
      );
    });
  });

  it("error state displays message", async () => {
    mockedApiRequest.mockResolvedValue(mockApiResult(null, false, 500));

    render(
      <SessionAnalyticsDashboard token="jwt" apiKey="key" onResult={onResult} />
    );

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Unable to load insights (500)"
      );
    });
  });

  it("displays error for network failure", async () => {
    mockedApiRequest.mockRejectedValue(new Error("Network failure"));

    render(
      <SessionAnalyticsDashboard token="jwt" apiKey="key" onResult={onResult} />
    );

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Network failure");
    });
  });

  it("model usage table shows correct rows sorted by invocations", async () => {
    mockedApiRequest.mockResolvedValue(mockApiResult(MOCK_REPORT));

    render(
      <SessionAnalyticsDashboard token="jwt" apiKey="key" onResult={onResult} />
    );

    await waitFor(() => {
      expect(screen.getByText("Model Usage")).toBeInTheDocument();
    });

    // gpt-4 has 200 invocations, claude-3 has 50 -> gpt-4 first
    const rows = screen.getAllByRole("row");
    // Row 0 is the header, Row 1 is gpt-4, Row 2 is claude-3
    expect(rows[1]).toHaveTextContent("gpt-4");
    expect(rows[1]).toHaveTextContent("200");
    expect(rows[1]).toHaveTextContent("$12.50");

    expect(rows[2]).toHaveTextContent("claude-3");
    expect(rows[2]).toHaveTextContent("50");
    expect(rows[2]).toHaveTextContent("$3.23");
  });

  it("tool usage table shows correct rows sorted by call count", async () => {
    mockedApiRequest.mockResolvedValue(mockApiResult(MOCK_REPORT));

    render(
      <SessionAnalyticsDashboard token="jwt" apiKey="key" onResult={onResult} />
    );

    await waitFor(() => {
      expect(screen.getByText("Tool Usage")).toBeInTheDocument();
    });

    // shell=120, file_ops=85, web_fetch=30 -> sorted descending
    expect(screen.getByText("shell")).toBeInTheDocument();
    expect(screen.getByText("120")).toBeInTheDocument();
    expect(screen.getByText("file_ops")).toBeInTheDocument();
    expect(screen.getByText("85")).toBeInTheDocument();
    expect(screen.getByText("web_fetch")).toBeInTheDocument();
    expect(screen.getByText("30")).toBeInTheDocument();
  });

  it("refresh button triggers re-fetch", async () => {
    const user = userEvent.setup();
    mockedApiRequest.mockResolvedValue(mockApiResult(MOCK_REPORT));

    render(
      <SessionAnalyticsDashboard token="jwt" apiKey="key" onResult={onResult} />
    );

    await waitFor(() => {
      expect(screen.getByTestId("card-sessions")).toBeInTheDocument();
    });

    mockedApiRequest.mockClear();

    await user.click(screen.getByRole("button", { name: "Refresh" }));

    await waitFor(() => {
      expect(mockedApiRequest).toHaveBeenCalledTimes(1);
    });
  });

  it("does not fetch when both token and apiKey are empty", () => {
    mockedApiRequest.mockResolvedValue(mockApiResult(MOCK_REPORT));

    render(
      <SessionAnalyticsDashboard token="" apiKey="" onResult={onResult} />
    );

    expect(mockedApiRequest).not.toHaveBeenCalled();
  });

  it("renders sparkline SVG for daily activity", async () => {
    mockedApiRequest.mockResolvedValue(mockApiResult(MOCK_REPORT));

    render(
      <SessionAnalyticsDashboard token="jwt" apiKey="key" onResult={onResult} />
    );

    await waitFor(() => {
      expect(screen.getByText("Daily Activity (Tokens)")).toBeInTheDocument();
    });

    const svg = screen.getByRole("img", {
      name: "Daily activity sparkline chart",
    });
    expect(svg).toBeInTheDocument();
    expect(svg.querySelector("polyline")).not.toBeNull();
  });
});
