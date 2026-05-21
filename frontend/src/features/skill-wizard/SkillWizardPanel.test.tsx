import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const { apiRequestMock } = vi.hoisted(() => ({
  apiRequestMock: vi.fn()
}));

vi.mock("../../lib/api", () => ({
  apiRequest: apiRequestMock
}));

import { SkillWizardPanel } from "./SkillWizardPanel";

function renderPanel(overrides: Partial<React.ComponentProps<typeof SkillWizardPanel>> = {}) {
  return render(
    <SkillWizardPanel
      token="token"
      apiKey=""
      onOpenSetup={vi.fn()}
      onResult={vi.fn()}
      {...overrides}
    />
  );
}

describe("SkillWizardPanel", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("prompts for credentials before authoring skills", () => {
    renderPanel({ token: "", apiKey: "" });

    expect(screen.getByText("Connect to the engine first")).toBeInTheDocument();
    expect(apiRequestMock).not.toHaveBeenCalled();
  });

  it("generates a preview from plain-language inputs", async () => {
    apiRequestMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      data: {
        skill: {
          name: "research-brief-writer",
          description: "Creates sourced briefs.",
          allowed_tools: ["web_search"],
          approval_required_for: ["file deletion"],
          tags: ["research"],
          category: "operator-authored",
          author: "operator",
          command_name: "research-brief-writer"
        },
        markdown: "# Research Brief Writer",
        installed: false,
        path: null,
        warnings: []
      }
    });

    renderPanel();

    await userEvent.type(screen.getByLabelText("Skill name"), "Research brief writer");
    await userEvent.type(screen.getByLabelText("Short description"), "Creates sourced briefs.");
    await userEvent.type(screen.getByLabelText("Plain-language goal"), "Research a topic and summarize sources.");
    await userEvent.type(screen.getByLabelText("Allowed tools, comma-separated"), "web_search");
    await userEvent.type(screen.getByLabelText("Tags"), "research");
    await userEvent.click(screen.getByRole("button", { name: "Preview skill" }));

    await waitFor(() => {
      expect(apiRequestMock).toHaveBeenCalledWith(
        expect.objectContaining({
          method: "POST",
          path: "/v1/skills/authoring/drafts",
          token: "token",
          apiKey: ""
        })
      );
    });
    expect(await screen.findByText("research-brief-writer")).toBeInTheDocument();
    expect(screen.getByText("/research-brief-writer")).toBeInTheDocument();
  });
});
