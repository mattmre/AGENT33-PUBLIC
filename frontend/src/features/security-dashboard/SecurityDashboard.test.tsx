import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SecurityDashboard, type SecurityFinding, type SecurityRun } from "./SecurityDashboard";

const API_BASE_URL = "http://agent33.test";

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: {
      "Content-Type": "application/json"
    },
    ...init
  });
}

function buildRun(overrides: Partial<SecurityRun> = {}): SecurityRun {
  return {
    id: "run-completed",
    status: "completed",
    profile: "quick",
    target: {
      repository_path: ".",
      commit_ref: "",
      branch: "main"
    },
    findings_count: 3,
    findings_summary: {
      critical: 2,
      high: 1,
      medium: 0,
      low: 1,
      info: 0
    },
    created_at: "2026-03-06T12:00:00Z",
    completed_at: "2026-03-06T12:05:00Z",
    error_message: "",
    metadata: {
      tools_executed: ["semgrep"],
      tool_warnings: []
    },
    ...overrides
  };
}

function buildFinding(overrides: Partial<SecurityFinding> = {}): SecurityFinding {
  return {
    id: "finding-1",
    run_id: "run-completed",
    severity: "high",
    category: "secrets",
    title: "Hardcoded credential",
    description: "A hardcoded credential was detected in the repository.",
    tool: "semgrep",
    file_path: "src/app.ts",
    line_number: 42,
    remediation: "Move the secret into a secure secret store.",
    cwe_id: "CWE-798",
    ...overrides
  };
}

describe("SecurityDashboard", () => {
  beforeEach(() => {
    window.__AGENT33_CONFIG__ = {
      API_BASE_URL
    };
  });

  it("loads scan history and aggregates severity totals from completed runs only", async () => {
    let resolveRuns: ((response: Response) => void) | undefined;
    const fetchMock = vi.fn(() => {
      return new Promise<Response>((resolve) => {
        resolveRuns = resolve;
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<SecurityDashboard token="test-token" />);

    expect(screen.getByText("Loading scan history...")).toBeInTheDocument();
    expect(resolveRuns).toBeDefined();
    resolveRuns!(jsonResponse([
      buildRun(),
      buildRun({
        id: "run-running",
        status: "running",
        findings_summary: {
          critical: 9,
          high: 9,
          medium: 9,
          low: 9,
          info: 9
        }
      })
    ]));

    expect(await screen.findByText("run-completed")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByText("Loading scan history...")).not.toBeInTheDocument();
    });

    expect(screen.getByText("Critical: 2")).toBeInTheDocument();
    expect(screen.getByText("High: 1")).toBeInTheDocument();
    expect(screen.getByText("Low: 1")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE_URL}/v1/component-security/runs?limit=20`,
      {
        headers: {
          Authorization: "Bearer test-token"
        }
      }
    );
  });

  it("loads findings after selecting a run", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse([buildRun()]))
      .mockResolvedValueOnce(jsonResponse({ findings: [buildFinding()] }));
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<SecurityDashboard token="test-token" />);

    await user.click(await screen.findByText("run-completed"));

    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      `${API_BASE_URL}/v1/component-security/runs/run-completed/findings`,
      {
        headers: {
          Authorization: "Bearer test-token"
        }
      }
    );
    expect(await screen.findByText("Hardcoded credential")).toBeInTheDocument();
    expect(screen.getByText("1 of 1 findings")).toBeInTheDocument();
  });

  it("surfaces backend quick-scan errors to the user", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(
        jsonResponse(
          {
            detail: "Scan failed due to policy"
          },
          { status: 400 }
        )
      );
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<SecurityDashboard token="test-token" />);

    expect(
      await screen.findByText('No scan runs yet. Click "Quick Scan" to start.')
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Quick Scan" }));

    expect(await screen.findByText("Scan failed due to policy")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      `${API_BASE_URL}/v1/component-security/runs`,
      expect.objectContaining({
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: "Bearer test-token"
        }
      })
    );
  });
});
