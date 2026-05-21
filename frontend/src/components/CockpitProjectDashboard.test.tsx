import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CockpitProjectDashboard } from "./CockpitProjectDashboard";
import { getWorkspaceSession } from "../data/workspaces";

describe("CockpitProjectDashboard", () => {
  it("summarizes the active workspace, permission mode, and next action", () => {
    render(
      <CockpitProjectDashboard
        workspace={getWorkspaceSession("shipyard")}
        permissionModeId="pr-first"
        onReviewCurrentWork={vi.fn()}
        onOpenWorkflows={vi.fn()}
        onOpenSafety={vi.fn()}
      />
    );

    expect(screen.getByRole("region", { name: "Project cockpit dashboard" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Multi-Agent Shipyard" })).toBeInTheDocument();
    expect(screen.getAllByText("PR-first implementation")).toHaveLength(3);
    expect(screen.getByText("3 tasks need attention")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Artifact timeline" })).toBeInTheDocument();
    expect(screen.getByText("Review timeline")).toBeInTheDocument();
    expect(screen.getByText("Artifact package ready")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Review outcome artifact: Artifact package ready" })
    ).toBeInTheDocument();
    expect(screen.getAllByText("Workspace template adapter").length).toBeGreaterThan(1);
    expect(screen.getByRole("region", { name: "Safety and coordination signals" })).toBeInTheDocument();
    expect(screen.getAllByText("1 cockpit item needs review.")).toHaveLength(2);
    expect(screen.getByRole("region", { name: "Safety gate summary" })).toHaveClass("safety-gate-indicator-review");
    expect(screen.getByLabelText("Needs review: 1")).toBeInTheDocument();
    expect(screen.getByLabelText("Top safety gate records")).toBeInTheDocument();
    expect(screen.getByText("WS")).toBeInTheDocument();
    expect(screen.getByText("shipyard")).toBeInTheDocument();
  });

  it("can render a summary-only cockpit view for the live shell", () => {
    render(
      <CockpitProjectDashboard
        workspace={getWorkspaceSession("shipyard")}
        permissionModeId="pr-first"
        onReviewCurrentWork={vi.fn()}
        onOpenWorkflows={vi.fn()}
        onOpenSafety={vi.fn()}
        showDetailSections={false}
      />
    );

    expect(screen.getByRole("region", { name: "Project cockpit dashboard" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Artifact timeline" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Safety and coordination signals" })).not.toBeInTheDocument();
  });

  it("routes dashboard actions through the existing cockpit surfaces", async () => {
    const user = userEvent.setup();
    const onReviewCurrentWork = vi.fn();
    const onOpenWorkflows = vi.fn();
    const onOpenSafety = vi.fn();

    render(
      <CockpitProjectDashboard
        workspace={getWorkspaceSession("solo-builder")}
        permissionModeId="ask"
        onReviewCurrentWork={onReviewCurrentWork}
        onOpenWorkflows={onOpenWorkflows}
        onOpenSafety={onOpenSafety}
      />
    );

    await user.click(screen.getByRole("button", { name: "Review task board" }));
    await user.click(screen.getByRole("button", { name: "Choose workflow" }));
    await user.click(screen.getByRole("button", { name: "Review approvals" }));

    expect(onReviewCurrentWork).toHaveBeenCalledTimes(1);
    expect(onOpenWorkflows).toHaveBeenCalledTimes(1);
    expect(onOpenSafety).toHaveBeenCalledTimes(1);
  });

  it("makes restricted mode blockers explicit before opening safety review", () => {
    render(
      <CockpitProjectDashboard
        workspace={getWorkspaceSession("solo-builder")}
        permissionModeId="restricted"
        onReviewCurrentWork={vi.fn()}
        onOpenWorkflows={vi.fn()}
        onOpenSafety={vi.fn()}
      />
    );

    expect(screen.getAllByText("1 cockpit safety item blocked.")).toHaveLength(2);
    expect(screen.getByLabelText("Blocked: 1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unlock a safer mode" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Choose workflow locked: Restricted mode keeps workflow launch locked/i })).toBeDisabled();
    expect(screen.getByText(/Restricted \/ high-risk locked: Unlock a safer mode before running high-risk actions/i)).toBeInTheDocument();
  });
});
