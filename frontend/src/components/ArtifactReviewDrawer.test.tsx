import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ArtifactReviewDrawer } from "./ArtifactReviewDrawer";
import { getWorkspaceSession } from "../data/workspaces";

describe("ArtifactReviewDrawer", () => {
  it("renders a review drawer scaffold for the active workspace", () => {
    render(<ArtifactReviewDrawer workspace={getWorkspaceSession("solo-builder")} permissionModeId="ask" />);

    expect(screen.getByRole("complementary", { name: "Artifact and review drawer" })).toBeInTheDocument();
    expect(screen.getByRole("tablist", { name: "Artifact drawer sections" })).toBeInTheDocument();
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", "artifact-drawer-tab-plan");
    expect(screen.getByText("Solo Builder")).toBeInTheDocument();
    expect(screen.getByText("Ask before action: Plans, setup guidance, and queued actions")).toBeInTheDocument();
    expect(screen.getByText("Plan artifact")).toBeInTheDocument();
    expect(screen.getAllByText("Capture the build request")).toHaveLength(2);
    expect(screen.getByText("Review scope and assumptions")).toBeInTheDocument();
  });

  it("switches between artifact sections without leaving the cockpit", async () => {
    const user = userEvent.setup();
    render(<ArtifactReviewDrawer workspace={getWorkspaceSession("test-review")} permissionModeId="workspace" />);

    await user.click(screen.getByRole("tab", { name: "Command Blocks" }));
    expect(screen.getByText("Command blocks")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Command Blocks" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Command Blocks" })).toHaveAttribute("tabindex", "0");
    expect(screen.getByText(/source agent, status, duration, and redaction state/i)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Command block evidence" })).toBeInTheDocument();
    expect(screen.getByText("Builder lane: Run checks")).toBeInTheDocument();
    expect(screen.getByText(/trace test-review-trace-quality-run/)).toBeInTheDocument();
    expect(screen.getByText("Failure: Prepare merge handoff is blocked before command evidence can complete.")).toBeInTheDocument();

    await user.keyboard("{End}");
    expect(screen.getByRole("tab", { name: "Outcome" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Done state")).toBeInTheDocument();
    expect(screen.getAllByText("Blocked with required action")).toHaveLength(2);

    await user.click(screen.getByRole("tab", { name: "Activity / Mailbox" }));
    expect(screen.getByText("Agent mailbox")).toBeInTheDocument();
    expect(screen.getByText("Quality Gate")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Activity evidence" })).toBeInTheDocument();
    expect(screen.getByText("Run checks")).toBeInTheDocument();
    expect(screen.getByText(/Mailbox handoff #2/)).toBeInTheDocument();
  });

  it("shows validation status details in the tests section", async () => {
    const user = userEvent.setup();
    render(<ArtifactReviewDrawer workspace={getWorkspaceSession("research-build")} permissionModeId="ask" />);

    await user.click(screen.getByRole("tab", { name: "Tests" }));

    expect(screen.getByRole("region", { name: "Validation status evidence" })).toBeInTheDocument();
    expect(screen.getByText("Scope checks")).toBeInTheDocument();
    expect(screen.getByText("Automated validation")).toBeInTheDocument();
    expect(screen.getByText("Reviewer decision")).toBeInTheDocument();
    expect(screen.getAllByText(/skipped \/ Waiting/)).toHaveLength(2);
  });

  it("groups approval safety evidence by permission gate status", async () => {
    const user = userEvent.setup();
    render(<ArtifactReviewDrawer workspace={getWorkspaceSession("solo-builder")} permissionModeId="ask" />);

    await user.click(screen.getByRole("tab", { name: "Approval" }));

    expect(screen.getByRole("region", { name: "Safety evidence" })).toBeInTheDocument();
    expect(screen.getByText("Confirm before tools or changes run.")).toBeInTheDocument();
    expect(screen.getByText("Needs review")).toBeInTheDocument();
    expect(screen.getByText("These items need an operator decision before AGENT33 continues.")).toBeInTheDocument();
    expect(screen.getByText("Next: User approval before commands, writes, or external changes")).toBeInTheDocument();
  });

  it("renders an explicit outcome handoff state", async () => {
    const user = userEvent.setup();
    render(<ArtifactReviewDrawer workspace={getWorkspaceSession("shipyard")} permissionModeId="pr-first" />);

    await user.click(screen.getByRole("tab", { name: "Outcome" }));

    expect(screen.getByRole("region", { name: "Outcome handoff" })).toBeInTheDocument();
    expect(screen.getAllByText("Artifact package ready").length).toBeGreaterThan(0);
    expect(screen.getByText("Next: Review the completed handoff")).toBeInTheDocument();
    expect(screen.getByText(/package ready \/ confirmed \/ 1 linked task/)).toBeInTheDocument();
  });
});
