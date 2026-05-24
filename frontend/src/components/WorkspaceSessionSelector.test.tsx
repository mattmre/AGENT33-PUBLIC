import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { WorkspaceSessionSelector } from "./WorkspaceSessionSelector";
import { getWorkspaceSession } from "../data/workspaces";

describe("WorkspaceSessionSelector", () => {
  it("renders the active workspace with beginner-readable context", () => {
    render(
      <WorkspaceSessionSelector
        selectedWorkspaceId="solo-builder"
        selectedWorkspace={getWorkspaceSession("solo-builder")}
        onSelectWorkspace={vi.fn()}
        onOpenRuns={vi.fn()}
        onOpenWorkflows={vi.fn()}
      />
    );

    expect(screen.getByRole("region", { name: "Workspace session" })).toBeInTheDocument();
    expect(screen.getByText("Local Shipyard")).toBeInTheDocument();
    expect(screen.getByText("Turn a plain-language idea into a guided build plan.")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Recommended workspace starter" })).toHaveTextContent("Guided build plan");
    expect(screen.getByRole("combobox", { name: "Active project template" })).toHaveValue("solo-builder");
    expect(screen.getByText("RUN")).toBeInTheDocument();
    expect(screen.getByText("REV")).toBeInTheDocument();
    expect(screen.getByText("BLK")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Workspace recovery" })).toHaveTextContent(
      "One safe resume point is ready."
    );
    expect(screen.getByText(/Resume planning \/ 1 agent \/ 30 min \/ 3 artifacts/)).toBeInTheDocument();
  });

  it("routes workspace changes and quick actions through callbacks", async () => {
    const user = userEvent.setup();
    const onSelectWorkspace = vi.fn();
    const onOpenRuns = vi.fn();
    const onOpenWorkflows = vi.fn();

    render(
      <WorkspaceSessionSelector
        selectedWorkspaceId="solo-builder"
        selectedWorkspace={getWorkspaceSession("solo-builder")}
        onSelectWorkspace={onSelectWorkspace}
        onOpenRuns={onOpenRuns}
        onOpenWorkflows={onOpenWorkflows}
      />
    );

    await user.selectOptions(screen.getByRole("combobox", { name: "Active project template" }), "shipyard");
    await user.click(screen.getByRole("button", { name: "Start Guided build plan" }));
    await user.click(screen.getByRole("button", { name: "View runs" }));

    expect(onSelectWorkspace).toHaveBeenCalledWith("shipyard");
    expect(onOpenWorkflows).toHaveBeenCalledWith(
      expect.objectContaining({
        id: "solo-guided-build",
        sourceLabel: "Workspace template: Guided build plan"
      })
    );
    expect(onOpenRuns).toHaveBeenCalledTimes(1);
  });
});
