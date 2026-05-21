import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DemoModePanel } from "./DemoModePanel";

describe("DemoModePanel", () => {
  it("shows a no-credentials first-success preview with artifacts", () => {
    render(
      <DemoModePanel
        onOpenModels={vi.fn()}
        onOpenWorkflowCatalog={vi.fn()}
        onOpenWorkflowStarter={vi.fn()}
      />
    );

    expect(screen.getByText("0 credentials needed")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Customer support dashboard" })).toBeInTheDocument();
    expect(screen.getByText("1 of 6")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Simulated run timeline" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Product brief" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /My first product idea/ })).toBeInTheDocument();
  });

  it("switches sample scenarios and sends a demo draft to Workflow Starter", async () => {
    const user = userEvent.setup();
    const onOpenWorkflowStarter = vi.fn();

    render(
      <DemoModePanel
        onOpenModels={vi.fn()}
        onOpenWorkflowCatalog={vi.fn()}
        onOpenWorkflowStarter={onOpenWorkflowStarter}
      />
    );

    await user.click(screen.getByRole("button", { name: /Landing page launch kit/ }));
    expect(screen.getByRole("heading", { name: "Landing page launch kit" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Customize this demo" }));
    expect(onOpenWorkflowStarter).toHaveBeenCalledWith(
      expect.objectContaining({
        id: "demo-landing-page",
        sourceLabel: "Demo Mode: Landing page launch kit"
      })
    );
  });

  it("filters scenarios for the selected role", () => {
    render(
      <DemoModePanel
        selectedRole="enterprise"
        onOpenModels={vi.fn()}
        onOpenWorkflowCatalog={vi.fn()}
        onOpenWorkflowStarter={vi.fn()}
      />
    );

    expect(screen.getByRole("button", { name: /Repo triage report/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Landing page launch kit/ })).not.toBeInTheDocument();
    expect(screen.getByText("1 of 2")).toBeInTheDocument();
  });
});
