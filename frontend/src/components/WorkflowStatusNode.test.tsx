import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("reactflow", () => ({
  __esModule: true,
  Handle: ({ type }: { type: string }) => <div data-testid={`handle-${type}`} />,
  Position: {
    Top: "top",
    Bottom: "bottom"
  }
}));

import { WorkflowStatusNode } from "./WorkflowStatusNode";

describe("WorkflowStatusNode", () => {
  it("renders retrying as an explicit status without the running pulse class", () => {
    const props = {
      data: { label: "Retry Step", status: "retrying" }
    } as any;
    const { container } = render(
      <WorkflowStatusNode {...props} />
    );

    expect(screen.getByRole("group", { name: "Retry Step: retrying" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("retrying");
    expect(container.firstChild).not.toHaveClass("wf-node-running");
  });

  it("renders running with the pulse class", () => {
    const props = {
      data: { label: "Running Step", status: "running" }
    } as any;
    const { container } = render(
      <WorkflowStatusNode {...props} />
    );

    expect(screen.getByRole("group", { name: "Running Step: running" })).toBeInTheDocument();
    expect(container.firstChild).toHaveClass("wf-node-running");
  });

  it("falls back to pending for unknown statuses", () => {
    const props = {
      data: { label: "Unknown Step", status: "mystery" }
    } as any;
    render(
      <WorkflowStatusNode {...props} />
    );

    expect(screen.getByRole("group", { name: "Unknown Step: pending" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("pending");
  });
});
