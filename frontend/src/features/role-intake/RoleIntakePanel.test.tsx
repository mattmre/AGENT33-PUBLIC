import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import { RoleIntakePanel } from "./RoleIntakePanel";

function renderPanel(overrides: Partial<ComponentProps<typeof RoleIntakePanel>> = {}) {
  return render(
    <RoleIntakePanel
      selectedRole={overrides.selectedRole ?? null}
      onSelectRole={overrides.onSelectRole ?? vi.fn()}
      onOpenDemo={overrides.onOpenDemo ?? vi.fn()}
      onOpenModels={overrides.onOpenModels ?? vi.fn()}
      onOpenWorkflowCatalog={overrides.onOpenWorkflowCatalog ?? vi.fn()}
      onOpenWorkflowStarter={overrides.onOpenWorkflowStarter ?? vi.fn()}
    />
  );
}

describe("RoleIntakePanel", () => {
  it("renders all role paths with beginner-readable labels", () => {
    renderPanel();

    expect(screen.getByRole("heading", { name: "Tell AGENT-33 who you are before choosing tools" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Founder/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Developer/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Agency/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Enterprise/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Operator/ })).toBeInTheDocument();
  });

  it("notifies the app when a user chooses a role", async () => {
    const user = userEvent.setup();
    const onSelectRole = vi.fn();
    renderPanel({ onSelectRole });

    await user.click(screen.getByRole("button", { name: /Developer/ }));

    expect(onSelectRole).toHaveBeenCalledWith("developer");
  });

  it("turns guided intake answers into a workflow starter draft", async () => {
    const onOpenWorkflowStarter = vi.fn();
    const onSelectRole = vi.fn();
    renderPanel({ selectedRole: "founder", onSelectRole, onOpenWorkflowStarter });

    fireEvent.change(screen.getByPlaceholderText("Example: Client portal MVP"), {
      target: { value: "Client portal MVP" }
    });
    fireEvent.change(
      screen.getByPlaceholderText("Example: A portal where clients fill out intake forms and see project status."),
      {
        target: { value: "A client portal for intake forms and project status." }
      }
    );
    fireEvent.change(screen.getByPlaceholderText("Example: business owner, client, project assistant"), {
      target: { value: "Business owner and client" }
    });
    fireEvent.change(
      screen.getByPlaceholderText("Example: product brief, screen list, first implementation tasks"),
      {
        target: { value: "Product brief and first build tasks" }
      }
    );
    await userEvent.click(screen.getByRole("button", { name: "Create guided workflow draft" }));

    expect(onSelectRole).toHaveBeenCalledWith("founder");
    expect(onOpenWorkflowStarter).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "client-portal-mvp",
        sourceLabel: "Guided intake: Client portal MVP"
      })
    );
  });
});
