import { describe, expect, it, vi } from "vitest";

import { apiRequest } from "../lib/api";
import { fetchWorkspaceRecoverySummary, fetchWorkspaceSessions } from "./workspaceApi";

vi.mock("../lib/api", () => ({
  apiRequest: vi.fn()
}));

const apiRequestMock = vi.mocked(apiRequest);

describe("workspace API integration", () => {
  it("maps live workspace records onto cockpit workspace summaries", async () => {
    apiRequestMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      durationMs: 8,
      url: "http://localhost:8000/v1/workspaces/",
      data: [
        {
          id: "solo-builder",
          name: "Live Local Shipyard",
          template: "Solo Builder",
          goal: "Live backend goal",
          status: "Running",
          agents: 5,
          tasks: 9,
          updated_at: "2026-05-24T00:00:00Z"
        }
      ]
    });

    const sessions = await fetchWorkspaceSessions("jwt", "");

    expect(apiRequestMock).toHaveBeenCalledWith({
      method: "GET",
      path: "/v1/workspaces/",
      token: "jwt",
      apiKey: ""
    });
    expect(sessions[0]).toEqual(
      expect.objectContaining({
        id: "solo-builder",
        name: "Live Local Shipyard",
        goal: "Live backend goal",
        status: "Running",
        agents: 5,
        tasks: 9,
        updatedLabel: "Live backend"
      })
    );
  });

  it("maps live recovery payloads into existing recovery card fields", async () => {
    apiRequestMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      durationMs: 7,
      url: "http://localhost:8000/v1/workspaces/shipyard/recovery",
      data: {
        workspace_id: "shipyard",
        primary_message: "1 recovery checkpoint requires attention.",
        next_action: "Review blocked checkpoints.",
        snapshots: [
          {
            id: "session-1",
            label: "Interrupted build",
            status: "blocked",
            resume_action: "Resume session",
            rollback_action: "Restore latest checkpoint",
            budget_label: "2 tasks / 4 events",
            artifact_count: 3
          }
        ]
      }
    });

    const summary = await fetchWorkspaceRecoverySummary("shipyard", "jwt", "api-key");

    expect(apiRequestMock).toHaveBeenCalledWith({
      method: "GET",
      path: "/v1/workspaces/{workspace_id}/recovery",
      pathParams: { workspace_id: "shipyard" },
      token: "jwt",
      apiKey: "api-key"
    });
    expect(summary.primaryMessage).toBe("1 recovery checkpoint requires attention.");
    expect(summary.snapshots[0]).toEqual(
      expect.objectContaining({
        id: "session-1",
        status: "blocked",
        resumeAction: "Resume session",
        artifactCount: 3
      })
    );
  });
});
