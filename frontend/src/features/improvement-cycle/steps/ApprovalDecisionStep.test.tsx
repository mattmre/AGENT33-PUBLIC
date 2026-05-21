import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiRequestMock } = vi.hoisted(() => ({
  apiRequestMock: vi.fn()
}));

vi.mock("../../../lib/api", () => ({
  apiRequest: apiRequestMock,
  getRuntimeConfig: () => ({ API_BASE_URL: "http://localhost:8000" }),
  buildUrl: (base: string, path: string) => `${base}${path}`,
  interpolatePath: (t: string, p: Record<string, string>) =>
    t.replace(/\{([^}]+)\}/g, (_, k: string) => p[k] ?? `{${k}}`)
}));

import { ApprovalDecisionStep } from "./ApprovalDecisionStep";

function makeResult(status: number, data: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    durationMs: 5,
    url: "http://localhost:8000/mock",
    data
  };
}

describe("ApprovalDecisionStep", () => {
  beforeEach(() => {
    apiRequestMock.mockReset();
  });

  it("disables form when no review ID is provided", () => {
    render(
      <ApprovalDecisionStep
        reviewId={null}
        reviewState=""
        token="jwt"
        apiKey=""
        onResult={vi.fn()}
        onDecisionComplete={vi.fn()}
      />
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Create and complete a review"
    );
    expect(screen.getByRole("button", { name: "Submit Decision" })).toBeDisabled();
  });

  it("disables form when review state is not approved", () => {
    render(
      <ApprovalDecisionStep
        reviewId="rev-1"
        reviewState="draft"
        token="jwt"
        apiKey=""
        onResult={vi.fn()}
        onDecisionComplete={vi.fn()}
      />
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      'Review is in "draft" state'
    );
    expect(screen.getByRole("button", { name: "Submit Decision" })).toBeDisabled();
  });

  it("enables form when review state is approved", () => {
    render(
      <ApprovalDecisionStep
        reviewId="rev-1"
        reviewState="approved"
        token="jwt"
        apiKey=""
        onResult={vi.fn()}
        onDecisionComplete={vi.fn()}
      />
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submit Decision" })).not.toBeDisabled();
  });

  it("submits an approved decision and calls onDecisionComplete", async () => {
    apiRequestMock.mockResolvedValueOnce(
      makeResult(200, {
        id: "rev-1",
        state: "approved",
        decision: "approved",
        approved_by: "operator",
        rationale: "Ship it."
      })
    );

    const onResult = vi.fn();
    const onDecisionComplete = vi.fn();

    render(
      <ApprovalDecisionStep
        reviewId="rev-1"
        reviewState="approved"
        token="jwt"
        apiKey=""
        onResult={onResult}
        onDecisionComplete={onDecisionComplete}
      />
    );

    await userEvent.click(screen.getByRole("button", { name: "Submit Decision" }));

    await waitFor(() => {
      expect(onDecisionComplete).toHaveBeenCalledWith("approved", "approved");
    });
    expect(apiRequestMock).toHaveBeenCalledTimes(1);
    const callArgs = apiRequestMock.mock.calls[0][0];
    expect(callArgs.method).toBe("POST");
    expect(callArgs.path).toBe("/v1/reviews/{review_id}/approve-with-rationale");
    expect(callArgs.pathParams).toEqual({ review_id: "rev-1" });
    const body = JSON.parse(callArgs.body);
    expect(body.decision).toBe("approved");
    expect(body).not.toHaveProperty("approver_id");
  });

  it("requires rationale for changes_requested decision", async () => {
    render(
      <ApprovalDecisionStep
        reviewId="rev-1"
        reviewState="approved"
        token="jwt"
        apiKey=""
        onResult={vi.fn()}
        onDecisionComplete={vi.fn()}
      />
    );

    await userEvent.selectOptions(
      screen.getByLabelText("Approval decision"),
      "changes_requested"
    );
    await userEvent.click(screen.getByRole("button", { name: "Submit Decision" }));

    expect(screen.getByText("Rationale is required for non-approved decisions.")).toBeInTheDocument();
    expect(apiRequestMock).not.toHaveBeenCalled();
  });

  it("shows modification summary field for changes_requested", async () => {
    render(
      <ApprovalDecisionStep
        reviewId="rev-1"
        reviewState="approved"
        token="jwt"
        apiKey=""
        onResult={vi.fn()}
        onDecisionComplete={vi.fn()}
      />
    );

    await userEvent.selectOptions(
      screen.getByLabelText("Approval decision"),
      "changes_requested"
    );
    expect(screen.getByLabelText("Modification summary")).toBeInTheDocument();
  });

  it("sends conditions as array in request body", async () => {
    apiRequestMock.mockResolvedValueOnce(
      makeResult(200, { id: "rev-1", state: "approved", decision: "approved" })
    );

    render(
      <ApprovalDecisionStep
        reviewId="rev-1"
        reviewState="approved"
        token="jwt"
        apiKey=""
        onResult={vi.fn()}
        onDecisionComplete={vi.fn()}
      />
    );

    await userEvent.type(screen.getByLabelText("Conditions"), "monitor, test");
    await userEvent.click(screen.getByRole("button", { name: "Submit Decision" }));

    await waitFor(() => expect(apiRequestMock).toHaveBeenCalledTimes(1));
    const body = JSON.parse(apiRequestMock.mock.calls[0][0].body);
    expect(body.conditions).toEqual(["monitor", "test"]);
  });

  it("displays error on API failure", async () => {
    apiRequestMock.mockResolvedValueOnce(
      makeResult(409, { detail: "Cannot apply rationale" })
    );

    render(
      <ApprovalDecisionStep
        reviewId="rev-1"
        reviewState="approved"
        token="jwt"
        apiKey=""
        onResult={vi.fn()}
        onDecisionComplete={vi.fn()}
      />
    );

    await userEvent.click(screen.getByRole("button", { name: "Submit Decision" }));

    await waitFor(() => {
      expect(screen.getByText("Cannot apply rationale")).toBeInTheDocument();
    });
  });
});
