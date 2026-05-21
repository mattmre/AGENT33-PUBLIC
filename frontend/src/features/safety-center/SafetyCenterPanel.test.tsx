import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const { apiRequestMock } = vi.hoisted(() => ({
  apiRequestMock: vi.fn()
}));

vi.mock("../../lib/api", () => ({
  apiRequest: apiRequestMock
}));

import { SafetyCenterPanel } from "./SafetyCenterPanel";

const pendingApproval = {
  approval_id: "APR-123",
  status: "pending",
  reason: "supervised_destructive",
  tool_name: "filesystem",
  operation: "delete",
  command: "Remove-Item C:\\temp\\unsafe.txt",
  requested_by: "research-agent",
  tenant_id: "tenant-a",
  details: "Delete generated artifact",
  created_at: "2026-01-01T12:00:00Z",
  expires_at: "2026-01-01T13:00:00Z",
  reviewed_by: "",
  reviewed_at: null,
  review_note: ""
};

const batchApproval = {
  approval_id: "APR-456",
  status: "pending",
  reason: "tool_policy_ask",
  tool_name: "filesystem",
  operation: "write",
  command: "Set-Content C:\\temp\\report.txt ok",
  requested_by: "ops-agent",
  tenant_id: "tenant-a",
  details: "Write a generated report",
  created_at: "2026-01-01T12:05:00Z",
  expires_at: "2026-01-01T13:05:00Z",
  reviewed_by: "",
  reviewed_at: null,
  review_note: ""
};

const approvedRouteMutation = {
  approval_id: "APR-789",
  status: "approved",
  reason: "route_mutation",
  tool_name: "route:auth.api-keys",
  operation: "create_api_key",
  command: "POST auth.api-keys",
  requested_by: "operator",
  tenant_id: "tenant-a",
  details: "Create a scoped integration key",
  created_at: "2026-01-01T12:00:00Z",
  expires_at: "2026-01-01T13:00:00Z",
  reviewed_by: "operator",
  reviewed_at: "2026-01-01T12:10:00Z",
  review_note: "Approved for a scoped integration rollout"
};

function renderPanel(overrides: Partial<React.ComponentProps<typeof SafetyCenterPanel>> = {}) {
  return render(
    <SafetyCenterPanel
      token="token"
      apiKey=""
      onOpenSetup={vi.fn()}
      onResult={vi.fn()}
      {...overrides}
    />
  );
}

describe("SafetyCenterPanel", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("prompts for credentials before loading approval state", () => {
    const onOpenSetup = vi.fn();

    renderPanel({ token: "", apiKey: "", onOpenSetup });

    expect(screen.getByText("Connect to the engine first")).toBeInTheDocument();
    expect(apiRequestMock).not.toHaveBeenCalled();
  });

  it("renders pending approval details and submits an approval decision", async () => {
    apiRequestMock
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        data: [pendingApproval]
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        data: {
          ...pendingApproval,
          status: "approved",
          reviewed_by: "operator",
          reviewed_at: "2026-01-01T12:10:00Z",
          review_note: "Reviewed command scope"
        }
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        data: []
      });

    renderPanel();

    expect(await screen.findAllByText("filesystem: delete")).toHaveLength(3);
    expect(screen.getByRole("heading", { name: "Decide the riskiest items first" })).toBeInTheDocument();
    expect(screen.getByText("1 high-risk item requires individual approval and usually a single_use token.")).toBeInTheDocument();
    expect(screen.getByText(/Decision mode: Individual approval only/)).toBeInTheDocument();
    expect(screen.getByText(/Token preset: single_use/)).toBeInTheDocument();
    expect(screen.getByText("Destructive or high-impact action")).toBeInTheDocument();
    expect(screen.getByText("Remove-Item C:\\temp\\unsafe.txt")).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Review note"), "Reviewed command scope");
    await userEvent.click(screen.getByRole("button", { name: "Approve action" }));

    await waitFor(() => {
      expect(apiRequestMock).toHaveBeenCalledWith({
        method: "POST",
        path: "/v1/approvals/tools/{approval_id}/decision",
        pathParams: { approval_id: "APR-123" },
        token: "token",
        apiKey: "",
        body: JSON.stringify({
          decision: "approve",
          review_note: "Reviewed command scope"
        })
      });
    });
  });

  it("submits a batch approval for low and medium risk items with a time-bound preset", async () => {
    apiRequestMock
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        data: [batchApproval]
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        data: {
          count: 1,
          results: [
            {
              ...batchApproval,
              status: "approved",
              reviewed_by: "operator",
              reviewed_at: "2026-01-01T12:10:00Z",
              review_note: "Safe to batch approve",
              approval_token: "batch-token-123",
              ttl_seconds: 900,
              one_time: false
            }
          ]
        }
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        data: [
          {
            ...batchApproval,
            status: "approved",
            reviewed_by: "operator",
            reviewed_at: "2026-01-01T12:10:00Z",
            review_note: "Safe to batch approve"
          }
        ]
      });

    renderPanel();

    expect(await screen.findByText(/1 low\/medium-risk item can use batch approval/)).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Batch review note"), "Safe to batch approve");
    await userEvent.click(screen.getByLabelText("Issue approval tokens for approved follow-through"));
    await userEvent.selectOptions(screen.getByLabelText("Time-bound preset"), "session_15m");
    await userEvent.click(screen.getByRole("button", { name: "Approve low/medium queue" }));

    await waitFor(() => {
      expect(apiRequestMock).toHaveBeenCalledWith(
        expect.objectContaining({
          method: "POST",
          path: "/v1/approvals/tools/batch-decision",
          token: "token",
          apiKey: "",
          body: JSON.stringify({
            approval_ids: ["APR-456"],
            decision: "approve",
            review_note: "Safe to batch approve",
            issue_tokens: true,
            token_preset: "session_15m"
          })
        })
      );
    });
  });

  it("issues a short-lived approval token for an approved route mutation", async () => {
    apiRequestMock
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        data: [approvedRouteMutation]
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        data: {
          ...approvedRouteMutation,
          approval_token: "route-token-abc",
          ttl_seconds: 300,
          one_time: true
        }
      });

    renderPanel();

    expect(await screen.findByText("Sensitive route mutation")).toBeInTheDocument();
    expect(screen.getAllByText(/X-Agent33-Approval-Token/).length).toBeGreaterThan(0);

    await userEvent.click(screen.getByRole("button", { name: "Issue approval token" }));

    await waitFor(() => {
      expect(apiRequestMock).toHaveBeenCalledWith(
        expect.objectContaining({
          method: "POST",
          path: "/v1/approvals/tools/{approval_id}/token",
          pathParams: { approval_id: "APR-789" },
          token: "token",
          apiKey: "",
          body: JSON.stringify({
            token_preset: "single_use"
          })
        })
      );
    });

    expect(await screen.findByDisplayValue("route-token-abc")).toBeInTheDocument();
  });
});
