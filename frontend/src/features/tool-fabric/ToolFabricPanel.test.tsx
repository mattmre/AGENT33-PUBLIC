import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const { apiRequestMock } = vi.hoisted(() => ({
  apiRequestMock: vi.fn()
}));

vi.mock("../../lib/api", () => ({
  apiRequest: apiRequestMock
}));

import { ToolFabricPanel } from "./ToolFabricPanel";

function renderPanel(overrides: Partial<React.ComponentProps<typeof ToolFabricPanel>> = {}) {
  return render(
    <ToolFabricPanel
      token="token"
      apiKey=""
      onOpenSetup={vi.fn()}
      onOpenTools={vi.fn()}
      onOpenSkills={vi.fn()}
      onOpenWorkflowStarter={vi.fn()}
      onResult={vi.fn()}
      {...overrides}
    />
  );
}

describe("ToolFabricPanel", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("prompts for credentials before resolving the fabric", () => {
    renderPanel({ token: "", apiKey: "" });

    expect(screen.getByText("Connect to the engine first")).toBeInTheDocument();
    expect(apiRequestMock).not.toHaveBeenCalled();
  });

  it("resolves tools, skills, and workflows from one objective", async () => {
    apiRequestMock
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        data: {
          query: "research competitors",
          matches: [
            {
              name: "web_search",
              description: "Search the web",
              score: 0.91,
              status: "active",
              version: "1.0.0",
              tags: ["research"]
            }
          ]
        }
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        data: {
          query: "research competitors",
          matches: [
            {
              name: "competitive-research",
              description: "Compare external projects",
              score: 0.82,
              version: "1.0.0",
              tags: ["research"],
              pack: null
            }
          ]
        }
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        data: {
          query: "research competitors",
          matches: [
            {
              name: "research-loop",
              description: "Research and synthesize",
              score: 0.77,
              source: "template",
              version: "1.0.0",
              tags: ["workflow"],
              source_path: "core/workflows/research-loop.yaml",
              pack: null
            }
          ]
        }
      });

    renderPanel();

    await userEvent.type(screen.getByLabelText("What do you want to accomplish?"), "research competitors");
    await userEvent.click(screen.getByRole("button", { name: "Resolve tool plan" }));

    await waitFor(() => {
      expect(apiRequestMock).toHaveBeenCalledTimes(3);
    });
    expect((await screen.findAllByText("web_search")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("competitive-research").length).toBeGreaterThan(0);
    expect(screen.getAllByText("research-loop").length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: "Trust, compatibility, and proof" })).toBeInTheDocument();
    expect(screen.getByText("3 ready resources, 0 requiring review.")).toBeInTheDocument();
    expect(screen.getByText("tool:web_search must appear in the run ledger proof before completion is accepted.")).toBeInTheDocument();
    expect(apiRequestMock).toHaveBeenCalledWith(
      expect.objectContaining({
        method: "GET",
        path: "/v1/discovery/tools",
        token: "token",
        apiKey: ""
      })
    );
  });
});
