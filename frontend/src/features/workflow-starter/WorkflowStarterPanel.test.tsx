import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const { apiRequestMock } = vi.hoisted(() => ({
  apiRequestMock: vi.fn()
}));

vi.mock("../../lib/api", () => ({
  apiRequest: apiRequestMock
}));

import { WorkflowStarterPanel } from "./WorkflowStarterPanel";
import { OPERATIONS_RECOVERY_FOCUS_STORAGE_KEY } from "../operations-hub/recoveryNavigation";

function renderPanel(overrides: Partial<React.ComponentProps<typeof WorkflowStarterPanel>> = {}) {
  return render(
    <WorkflowStarterPanel
      token="token"
      apiKey=""
      onOpenSetup={vi.fn()}
      onOpenSpawner={vi.fn()}
      onOpenOperations={vi.fn()}
      onResult={vi.fn()}
      {...overrides}
    />
  );
}

describe("WorkflowStarterPanel", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("prompts for credentials before creating workflows", () => {
    renderPanel({ token: "", apiKey: "" });

    expect(screen.getByText("Connect to the engine first")).toBeInTheDocument();
    expect(apiRequestMock).not.toHaveBeenCalled();
  });

  it("recommends and creates a workflow from a plain-language goal", async () => {
    apiRequestMock
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        data: {
          query: "research",
          matches: [
            {
              name: "research-template",
              description: "Research template",
              score: 0.8,
              source: "template",
              version: "1.0.0",
              tags: ["research"],
              source_path: "core/workflows/research.yaml",
              pack: null
            }
          ]
        }
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        data: {
          query: "research",
          matches: [
            {
              name: "web-research",
              description: "Search and summarize sources",
              score: 0.7,
              version: "1.0.0",
              tags: ["research"],
              pack: null
            }
          ]
        }
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 201,
        data: {
          name: "weekly-agent-market-scan",
          version: "1.0.0",
          step_count: 4,
          created: true
        }
      });

    renderPanel();

    await userEvent.type(screen.getByLabelText("Workflow name"), "weekly-agent-market-scan");
    await userEvent.type(
      screen.getByLabelText("Goal"),
      "Track agent OS and MCP changes weekly."
    );
    await userEvent.click(screen.getByRole("button", { name: "Recommend plan" }));

    expect(await screen.findByText("research-template")).toBeInTheDocument();
    expect(screen.getByText("web-research")).toBeInTheDocument();
    expect(screen.getByText("weekly-agent-market-scan")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Create workflow" }));

    await waitFor(() => {
      expect(apiRequestMock).toHaveBeenCalledWith(
        expect.objectContaining({
          method: "POST",
          path: "/v1/workflows/",
          token: "token",
          apiKey: ""
        })
      );
    });
    expect(await screen.findByText("weekly-agent-market-scan created with 4 steps.")).toBeInTheDocument();
  });

  it("preserves outcome pack context in created workflow metadata and activity labels", async () => {
    const onResult = vi.fn();
    apiRequestMock.mockResolvedValueOnce({
      ok: true,
      status: 201,
      data: {
        name: "founder-mvp-builder",
        version: "1.0.0",
        step_count: 3,
        created: true
      }
    });

    renderPanel({
      onResult,
      initialDraft: {
        id: "outcome-founder-mvp-builder",
        name: "founder-mvp-builder",
        goal: "Create the first MVP plan.",
        kind: "automation-loop",
        output: "MVP brief; First sprint plan",
        author: "AGENT-33",
        sourceLabel: "Outcome pack: Founder MVP Builder",
        sourcePack: "official-outcome-packs",
        sourcePackVersion: "1.0.0",
        sourceOutcomeId: "founder-mvp-builder"
      }
    });

    expect(screen.getByText("Loaded starter: Outcome pack: Founder MVP Builder")).toBeInTheDocument();
    expect(screen.getByText("Pack: official-outcome-packs v1.0.0")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Create workflow" }));

    await waitFor(() => {
      expect(apiRequestMock).toHaveBeenCalledWith(
        expect.objectContaining({
          method: "POST",
          path: "/v1/workflows/"
        })
      );
    });

    const body = JSON.parse(apiRequestMock.mock.calls[0][0].body as string) as {
      metadata: { tags: string[] };
    };
    expect(body.metadata.tags).toEqual(
      expect.arrayContaining([
        "pack:official-outcome-packs",
        "pack-version:1.0.0",
        "outcome:founder-mvp-builder"
      ])
    );
    expect(onResult).toHaveBeenCalledWith(
      "Workflow Starter - Create Workflow from official-outcome-packs",
      expect.objectContaining({ status: 201 })
    );
  });

  it("shows the product-builder lifecycle from an incoming draft", () => {
    renderPanel({
      initialDraft: {
        id: "guided-brief-1",
        name: "client-portal-mvp",
        goal: "Create the first client portal plan.",
        kind: "automation-loop",
        output: "Product brief and implementation plan",
        author: "role-intake",
        sourceLabel: "Guided intake: Client portal MVP",
        lifecyclePlan: {
          brief: ["Idea: client portal", "Audience: owner and client"],
          plan: ["Prepare product brief and build plan"],
          preview: ["Validate inputs before tools run"],
          handoff: ["Create an editable workflow after review"]
        }
      }
    });

    expect(screen.getByRole("heading", { name: "Product builder lifecycle" })).toBeInTheDocument();
    expect(screen.getByText("Brief")).toBeInTheDocument();
    expect(screen.getByText("Plan")).toBeInTheDocument();
    expect(screen.getByText("Preview")).toBeInTheDocument();
    expect(screen.getByText("Execution handoff")).toBeInTheDocument();
    expect(screen.getByText("Validate inputs before tools run")).toBeInTheDocument();
  });

  it("routes recovery calls to the focused Operations recovery panel", async () => {
    const onOpenOperations = vi.fn();
    apiRequestMock
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        data: {
          overall_complete: true,
          completed_count: 4,
          total_count: 4,
          steps: [
            {
              step_id: "OB-02",
              title: "Model provider connected",
              completed: true
            }
          ]
        }
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        data: {
          overall_state: "ready",
          summary: "A local model path is ready.",
          ready_provider_count: 1,
          attention_provider_count: 0,
          total_model_count: 2,
          providers: [
            {
              provider: "ollama",
              label: "Ollama",
              state: "available",
              ok: true,
              base_url: "http://localhost:11434",
              model_count: 2,
              message: "Connected",
              action: "None"
            }
          ]
        }
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        data: [
          {
            session_id: "session-42",
            purpose: "Resume market scan",
            status: "suspended",
            started_at: "2026-04-28T14:00:00Z",
            updated_at: "2026-04-28T15:30:00Z",
            ended_at: null,
            task_count: 5,
            tasks_completed: 3,
            event_count: 12,
            parent_session_id: null,
            tenant_id: "tenant-1"
          }
        ]
      });

    renderPanel({ onOpenOperations });

    await userEvent.click(screen.getByRole("button", { name: "Refresh launch checks" }));
    expect(await screen.findByRole("button", { name: "Open recovery panel" })).toBeInTheDocument();

    await userEvent.click(screen.getAllByRole("button", { name: "Open recovery panel" })[0]);

    expect(onOpenOperations).toHaveBeenCalledTimes(1);
    expect(window.sessionStorage.getItem(OPERATIONS_RECOVERY_FOCUS_STORAGE_KEY)).toBe(
      "session-recovery"
    );
  });
});
