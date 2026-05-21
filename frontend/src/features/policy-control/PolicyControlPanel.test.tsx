import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import { PolicyControlPanel } from "./PolicyControlPanel";

const MOCK_POLICY = {
  tool_use_mode: "audit",
  evidence_required: true,
  review_authority: "user",
  policy_shards: [
    { id: "policy.tool-use.default", label: "Tool use", mode: "Schema validation and audit receipts" },
    { id: "policy.evidence.default", label: "Evidence gate", mode: "Completion requires proof" },
    { id: "policy.review.default", label: "Review", mode: "High-risk work asks for review" }
  ],
  collaboration_modes: [
    { id: "paired", label: "Paired", detail: "Frequent interaction with dry-run authority" },
    { id: "autonomous", label: "Autonomous", detail: "Approved writes with fail-closed completion" },
    { id: "review_only", label: "Review only", detail: "Read-only inspection and recommendations" },
    { id: "approval_required", label: "Approval required", detail: "Dry runs until a mutation is approved" },
    { id: "background_worker", label: "Background worker", detail: "Periodic check-ins with fail-closed proof" }
  ]
};

describe("PolicyControlPanel", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => MOCK_POLICY
      })
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders header without a token", () => {
    render(<PolicyControlPanel />);
    expect(screen.getByText("Authority, gates, and collaboration modes")).toBeInTheDocument();
  });

  it("fetches and renders policy shards and collaboration modes", async () => {
    render(<PolicyControlPanel token="test-token" />);

    await waitFor(() => {
      expect(screen.getByText("Tool use")).toBeInTheDocument();
    });

    expect(screen.getByText("Evidence gate")).toBeInTheDocument();
    expect(screen.getByText("Autonomous")).toBeInTheDocument();
    expect(screen.getByText("Approval required")).toBeInTheDocument();
  });

  it("calls the API with Authorization header when token is provided", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => MOCK_POLICY
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<PolicyControlPanel token="my-bearer-token" />);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/v1/policy/active"),
        expect.objectContaining({
          headers: { Authorization: "Bearer my-bearer-token" }
        })
      );
    });
  });

  it("renders unavailable message on API error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false })
    );

    render(<PolicyControlPanel token="test-token" />);

    await waitFor(() => {
      expect(screen.getByText(/Policy state unavailable/i)).toBeInTheDocument();
    });
  });
});
