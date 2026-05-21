import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { OUTCOME_WORKFLOWS } from "../outcome-home/catalog";
import { ProductWorkflowDetail } from "./ProductWorkflowDetail";

describe("ProductWorkflowDetail", () => {
  it("shows productized inputs, outputs, estimates, dry-run preview, and starter pack", () => {
    render(
      <ProductWorkflowDetail
        workflow={OUTCOME_WORKFLOWS[0]}
        onUseWorkflow={vi.fn()}
        onOpenSetup={vi.fn()}
        onOpenOperations={vi.fn()}
      />
    );

    expect(screen.getByRole("heading", { name: "What you need before launch" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Example outputs" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Dry-run preview" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Starter pack" })).toBeInTheDocument();
    expect(screen.getByText(/\$1-\$6 estimated model use/)).toBeInTheDocument();
  });

  it("hands the selected workflow to Workflow Starter", async () => {
    const user = userEvent.setup();
    const onUseWorkflow = vi.fn();
    render(
      <ProductWorkflowDetail
        workflow={OUTCOME_WORKFLOWS[0]}
        onUseWorkflow={onUseWorkflow}
        onOpenSetup={vi.fn()}
        onOpenOperations={vi.fn()}
      />
    );

    await user.click(screen.getByRole("button", { name: "Customize in Workflow Starter" }));

    expect(onUseWorkflow).toHaveBeenCalledWith(OUTCOME_WORKFLOWS[0]);
  });
});
