import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiRequestMock } = vi.hoisted(() => ({
  apiRequestMock: vi.fn()
}));

vi.mock("../../lib/api", () => ({
  apiRequest: apiRequestMock
}));

import { ImprovementCycleWizard } from "./ImprovementCycleWizard";

function makeResult(status: number, data: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    durationMs: 5,
    url: "http://localhost:8000/mock",
    data
  };
}

function makeReviewDetail(overrides: Record<string, unknown> = {}) {
  return {
    id: "rev-123",
    task_id: "session58-phase26-review",
    branch: "codex/session58-phase26-wizard",
    state: "draft",
    artifacts: [
      {
        kind: "explanation",
        artifact_id: "expl-123",
        label: "plan-review",
        mode: "plan_review"
      }
    ],
    risk_assessment: {
      risk_level: "none",
      triggers_identified: [],
      l1_required: false,
      l2_required: false
    },
    l1_review: {
      reviewer_id: "",
      reviewer_role: "",
      decision: "",
      comments: "",
      issues_found: []
    },
    l2_review: {
      reviewer_id: "",
      reviewer_role: "",
      decision: "",
      comments: "",
      issues_found: []
    },
    final_signoff: {
      approved_by: "",
      approval_type: "",
      conditions: []
    },
    ...overrides
  };
}

describe("ImprovementCycleWizard", () => {
  beforeEach(() => {
    apiRequestMock.mockReset();
  });

  it("generates a plan review artifact and creates a linked review", async () => {
    apiRequestMock
      .mockResolvedValueOnce(
        makeResult(201, {
          id: "expl-123",
          entity_type: "workflow",
          entity_id: "improvement-cycle-session58",
          content: "<html><body>Artifact preview</body></html>",
          mode: "plan_review",
          fact_check_status: "verified"
        })
      )
      .mockResolvedValueOnce(
        makeResult(201, {
          id: "rev-123",
          state: "draft",
          task_id: "session58-phase26-review",
          artifacts: [
            {
              kind: "explanation",
              artifact_id: "expl-123",
              label: "plan-review",
              mode: "plan_review"
            }
          ]
        })
      )
      .mockResolvedValueOnce(makeResult(200, makeReviewDetail()));

    render(
      <ImprovementCycleWizard token="jwt-token" apiKey="" onResult={vi.fn()} />
    );

    await userEvent.click(screen.getByRole("button", { name: "Generate artifact" }));

    await screen.findByText("expl-123");
    expect(apiRequestMock.mock.calls[0][0]).toMatchObject({
      method: "POST",
      path: "/v1/explanations/plan-review",
      token: "jwt-token"
    });
    expect(JSON.parse(apiRequestMock.mock.calls[0][0].body as string)).toMatchObject({
      entity_type: "workflow",
      entity_id: "improvement-cycle-session58"
    });

    await userEvent.click(screen.getByRole("button", { name: "Create linked review" }));

    await screen.findByText("rev-123");
    expect(apiRequestMock.mock.calls[1][0]).toMatchObject({
      method: "POST",
      path: "/v1/reviews/"
    });
    expect(JSON.parse(apiRequestMock.mock.calls[1][0].body as string)).toMatchObject({
      task_id: "session58-phase26-review",
      branch: "codex/session58-phase26-wizard",
      artifacts: [
        {
          kind: "explanation",
          artifact_id: "expl-123",
          label: "plan-review",
          mode: "plan_review"
        }
      ]
    });
  });

  it("surfaces the L2 path for a high-risk review", async () => {
    apiRequestMock
      .mockResolvedValueOnce(
        makeResult(201, {
          id: "expl-123",
          entity_type: "workflow",
          entity_id: "improvement-cycle-session58",
          content: "<html><body>Artifact preview</body></html>",
          mode: "plan_review",
          fact_check_status: "verified"
        })
      )
      .mockResolvedValueOnce(
        makeResult(201, {
          id: "rev-123",
          state: "draft",
          task_id: "session58-phase26-review",
          artifacts: []
        })
      )
      .mockResolvedValueOnce(makeResult(200, makeReviewDetail()))
      .mockResolvedValueOnce(
        makeResult(200, {
          id: "rev-123",
          risk_level: "high",
          l1_required: true,
          l2_required: true,
          triggers: ["security", "api-public"]
        })
      )
      .mockResolvedValueOnce(
        makeResult(
          200,
          makeReviewDetail({
            risk_assessment: {
              risk_level: "high",
              triggers_identified: ["security", "api-public"],
              l1_required: true,
              l2_required: true
            }
          })
        )
      );

    render(
      <ImprovementCycleWizard token="jwt-token" apiKey="" onResult={vi.fn()} />
    );

    await userEvent.click(screen.getByRole("button", { name: "Generate artifact" }));
    await screen.findByText("expl-123");
    await userEvent.click(screen.getByRole("button", { name: "Create linked review" }));
    await screen.findByText("rev-123");

    await userEvent.click(screen.getByLabelText("Security"));
    await userEvent.click(screen.getByLabelText("Api Public"));
    await userEvent.click(screen.getByRole("button", { name: "Assess selected risk triggers" }));

    await screen.findByText((_, node) => node?.textContent === "L2 required: Yes");
    expect(apiRequestMock.mock.calls[3][0]).toMatchObject({
      method: "POST",
      path: "/v1/reviews/{review_id}/assess",
      pathParams: { review_id: "rev-123" }
    });
    expect(JSON.parse(apiRequestMock.mock.calls[3][0].body as string)).toEqual({
      triggers: ["security", "api-public"]
    });
    expect(
      screen.getByText((_, node) => node?.textContent === "L2 required: Yes")
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Assign L2 reviewer" })).not.toBeDisabled();
  });

  it("lists pending tool approvals and lets operators approve them", async () => {
    apiRequestMock
      .mockResolvedValueOnce(
        makeResult(200, [
          {
            approval_id: "APR-123",
            status: "pending",
            reason: "tool_policy_ask",
            tool_name: "shell",
            operation: "run",
            command: "git status",
            requested_by: "agent",
            details: "Repository inspection requested.",
            created_at: "2026-03-08T12:00:00Z",
            expires_at: "2026-03-08T13:00:00Z",
            review_note: ""
          }
        ])
      )
      .mockResolvedValueOnce(
        makeResult(200, {
          approval_id: "APR-123",
          status: "approved"
        })
      );

    render(
      <ImprovementCycleWizard token="jwt-token" apiKey="" onResult={vi.fn()} />
    );

    await userEvent.click(screen.getByRole("button", { name: "Refresh pending approvals" }));

    await screen.findByText("APR-123");
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => {
      expect(screen.queryByText("APR-123")).not.toBeInTheDocument();
    });
    expect(apiRequestMock.mock.calls[1][0]).toMatchObject({
      method: "POST",
      path: "/v1/approvals/tools/{approval_id}/decision",
      pathParams: { approval_id: "APR-123" }
    });
    expect(JSON.parse(apiRequestMock.mock.calls[1][0].body as string)).toMatchObject({
      decision: "approve"
    });
  });
});
