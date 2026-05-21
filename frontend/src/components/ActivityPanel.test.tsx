import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ActivityItem } from "../types";
import { ActivityPanel } from "./ActivityPanel";

vi.mock("./ObservationStream", () => ({
  ObservationStream: () => <div data-testid="observation-stream">Observations</div>
}));

const activity: ActivityItem[] = [
  {
    id: "call-1",
    at: "10:15:00 AM",
    label: "Create Token",
    status: 200,
    durationMs: 18,
    url: "/v1/auth/token"
  }
];

describe("ActivityPanel", () => {
  it("renders the live shell summary and recent activity", () => {
    render(
      <ActivityPanel
        token="jwt"
        activity={activity}
        activeSurfaceLabel="Authentication"
        contextLabel="Token and API key control"
        operatorMode="pro"
        onOpenOperations={vi.fn()}
        onOpenSafety={vi.fn()}
        onOpenWorkflowCatalog={vi.fn()}
      />
    );

    expect(screen.getByRole("complementary", { name: "Activity and runtime signals" })).toHaveTextContent(
      "Authentication"
    );
    expect(screen.getByText("Token and API key control")).toBeInTheDocument();
    expect(screen.getByText("Create Token")).toBeInTheDocument();
    expect(screen.getByText("/v1/auth/token")).toBeInTheDocument();
    expect(screen.getByTestId("observation-stream")).toBeInTheDocument();
  });

  it("routes summary actions through the shared callbacks", async () => {
    const user = userEvent.setup();
    const onOpenOperations = vi.fn();
    const onOpenSafety = vi.fn();
    const onOpenWorkflowCatalog = vi.fn();

    render(
      <ActivityPanel
        token={null}
        activity={[]}
        activeSurfaceLabel="No matching domain"
        contextLabel="Adjust the filter to restore a visible technical surface."
        operatorMode="beginner"
        onOpenOperations={onOpenOperations}
        onOpenSafety={onOpenSafety}
        onOpenWorkflowCatalog={onOpenWorkflowCatalog}
      />
    );

    await user.click(screen.getByRole("button", { name: "Open runs" }));
    await user.click(screen.getByRole("button", { name: "Review gates" }));
    await user.click(screen.getByRole("button", { name: "Browse workflows" }));

    expect(onOpenOperations).toHaveBeenCalledTimes(1);
    expect(onOpenSafety).toHaveBeenCalledTimes(1);
    expect(onOpenWorkflowCatalog).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/No calls yet/)).toBeInTheDocument();
  });
});
