import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ShipyardLaneScaffold } from "./ShipyardLaneScaffold";
import { getWorkspaceSession } from "../data/workspaces";

describe("ShipyardLaneScaffold", () => {
  it("renders Drydock-style role lanes for the selected workspace", () => {
    render(
      <ShipyardLaneScaffold
        workspace={getWorkspaceSession("shipyard")}
        permissionModeId="pr-first"
        onOpenWorkflows={vi.fn()}
        onOpenSafety={vi.fn()}
      />
    );

    expect(screen.getByRole("region", { name: "Shipyard lanes" })).toBeInTheDocument();
    expect(screen.getByText("Shipyard command lanes")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Coordinator lane" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Scout lane" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Builder lane" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Reviewer lane" })).toBeInTheDocument();
    expect(screen.getByText("Agent: Coordinator")).toBeInTheDocument();
    expect(screen.getByText("Scout implementation risks")).toBeInTheDocument();
    expect(screen.getAllByText("Running").length).toBeGreaterThan(0);
    expect(screen.getByText("Expected output: Implementation slice, validation commands, and changed artifacts.")).toBeInTheDocument();
  });

  it("keeps empty role lanes beginner-readable", () => {
    render(
      <ShipyardLaneScaffold
        workspace={getWorkspaceSession("solo-builder")}
        permissionModeId="ask"
        onOpenWorkflows={vi.fn()}
        onOpenSafety={vi.fn()}
      />
    );

    expect(screen.getByText("Scout lane")).toBeInTheDocument();
    expect(screen.getAllByText("No tasks assigned to this role yet.").length).toBeGreaterThan(0);
  });

  it("routes lane actions through existing cockpit surfaces", async () => {
    const user = userEvent.setup();
    const onOpenWorkflows = vi.fn();
    const onOpenSafety = vi.fn();

    render(
      <ShipyardLaneScaffold
        workspace={getWorkspaceSession("test-review")}
        permissionModeId="workspace"
        onOpenWorkflows={onOpenWorkflows}
        onOpenSafety={onOpenSafety}
      />
    );

    await user.click(screen.getByRole("button", { name: "Launch workflow" }));
    await user.click(screen.getByRole("button", { name: "Check approvals" }));

    expect(onOpenWorkflows).toHaveBeenCalledTimes(1);
    expect(onOpenSafety).toHaveBeenCalledTimes(1);
  });

  it("locks workflow launch in restricted mode with an explanatory label", () => {
    render(
      <ShipyardLaneScaffold
        workspace={getWorkspaceSession("test-review")}
        permissionModeId="restricted"
        onOpenWorkflows={vi.fn()}
        onOpenSafety={vi.fn()}
      />
    );

    const launchButton = screen.getByRole("button", {
      name: /Launch workflow locked: Restricted mode keeps workflow launch locked/i
    });
    expect(launchButton).toBeDisabled();
    expect(launchButton).toHaveAccessibleDescription("Restricted mode keeps workflow launch locked.");
  });
});
