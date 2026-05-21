import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { getWorkspaceSession } from "../data/workspaces";
import { WorkspaceTaskBoard } from "./WorkspaceTaskBoard";

describe("WorkspaceTaskBoard", () => {
  it("renders task lanes and agent roster for the selected workspace", () => {
    render(
      <WorkspaceTaskBoard
        workspace={getWorkspaceSession("shipyard")}
        permissionModeId="pr-first"
        onOpenSafety={vi.fn()}
        onOpenWorkflows={vi.fn()}
      />
    );

    expect(screen.getByRole("region", { name: "Multi-Agent Shipyard task board" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Multi-Agent Shipyard recommended starters" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Multi-Agent Shipyard recovery controls" })).toHaveTextContent(
      "Multi-agent work has two recoverable checkpoints."
    );
    expect(screen.getByText("Active build lane")).toBeInTheDocument();
    expect(screen.getByText("Restore last merged baseline")).toBeInTheDocument();
    expect(screen.getByText("4 agents / 60 min")).toBeInTheDocument();
    expect(screen.getByText("Multi-agent slice orchestration")).toBeInTheDocument();
    expect(screen.getByText(/Starts with Break work into lanes/)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Running tasks" })).toBeInTheDocument();
    expect(screen.getByText("Build the next slice")).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Workspace agent roster" })).toBeInTheDocument();
    expect(screen.getByText(/Who does what in Multi-Agent Shipyard/)).toBeInTheDocument();
    expect(screen.getByText("Sequences work and prevents PR drift.")).toBeInTheDocument();
  });

  it("routes board actions through callbacks", async () => {
    const user = userEvent.setup();
    const onOpenSafety = vi.fn();
    const onOpenWorkflows = vi.fn();

    render(
      <WorkspaceTaskBoard
        workspace={getWorkspaceSession("solo-builder")}
        permissionModeId="ask"
        onOpenSafety={onOpenSafety}
        onOpenWorkflows={onOpenWorkflows}
      />
    );

    await user.click(screen.getByRole("button", { name: "Choose workflow" }));
    await user.click(screen.getByRole("button", { name: "Use starter: Guided build plan" }));
    await user.click(screen.getByRole("button", { name: "Review approvals" }));

    expect(onOpenWorkflows).toHaveBeenCalledTimes(2);
    expect(onOpenWorkflows.mock.calls[0]).toEqual([]);
    expect(onOpenWorkflows).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({
        id: "solo-guided-build",
        sourceLabel: "Workspace template: Guided build plan"
      })
    );
    expect(onOpenSafety).toHaveBeenCalledTimes(1);
  });

  it("shows permission gate explanations on task actions", () => {
    render(
      <WorkspaceTaskBoard
        workspace={getWorkspaceSession("solo-builder")}
        permissionModeId="observe"
        onOpenSafety={vi.fn()}
        onOpenWorkflows={vi.fn()}
      />
    );

    expect(screen.getByRole("button", { name: /Choose workflow locked: Observe only keeps workflow launch read-only/i })).toBeDisabled();
    expect(screen.getAllByRole("button", { name: /Use starter locked: .*Observe only keeps workflow launch read-only/i })).toHaveLength(2);
    expect(screen.getByRole("button", { name: /Use starter locked: .*Guided build plan/i })).toHaveAccessibleDescription(
      "Observe only keeps workflow launch read-only until you choose a more active mode."
    );
    expect(screen.getByRole("button", { name: /Choose workflow locked/i })).toHaveAccessibleDescription(
      "Observe only keeps workflow launch read-only until you choose a more active mode."
    );
    expect(screen.getByText("Command run")).toBeInTheDocument();
    expect(screen.getByText("Observe only blocks command execution.")).toBeInTheDocument();
    expect(screen.getByText("Observe only cannot approve actions.")).toBeInTheDocument();
  });
});
