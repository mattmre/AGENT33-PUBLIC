import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { DomainConfig } from "../../types";
import { AdvancedControlPlanePanel, type OperatorMode } from "./AdvancedControlPlanePanel";

vi.mock("../../components/HealthPanel", () => ({
  HealthPanel: () => <div data-testid="health-panel">Health</div>
}));

vi.mock("../../components/DomainPanel", () => ({
  DomainPanel: ({
    domain,
    externalFilter
  }: {
    domain: DomainConfig;
    externalFilter?: string;
  }) => (
    <div data-testid="domain-panel">
      {domain.title}:{externalFilter}
    </div>
  )
}));

vi.mock("../../components/ActivityPanel", () => ({
  ActivityPanel: ({
    activeSurfaceLabel,
    contextLabel
  }: {
    activeSurfaceLabel: string;
    contextLabel: string;
  }) => (
    <div data-testid="activity-panel">
      {activeSurfaceLabel}:{contextLabel}
    </div>
  )
}));

const domains: DomainConfig[] = [
  {
    id: "auth",
    title: "Authentication",
    description: "Token and API key control",
    operations: [
      {
        id: "auth-token",
        title: "Create Token",
        method: "POST",
        path: "/v1/auth/token",
        description: "Create a token"
      }
    ]
  },
  {
    id: "memory",
    title: "Memory",
    description: "Memory store operations",
    operations: [
      {
        id: "memory-delete",
        title: "Delete Memory",
        method: "DELETE",
        path: "/v1/memory/{id}",
        description: "Delete a memory item"
      }
    ]
  }
];

function renderPanel(overrides: Partial<{ operatorMode: OperatorMode; selectedDomainId: string }> = {}) {
  return render(
    <AdvancedControlPlanePanel
      domains={domains}
      selectedDomainId={overrides.selectedDomainId ?? "auth"}
      token="jwt"
      apiKey=""
      activity={[]}
      operatorMode={overrides.operatorMode ?? "pro"}
      onOperatorModeChange={vi.fn()}
      onSelectedDomainChange={vi.fn()}
      onOpenModels={vi.fn()}
      onOpenWorkflowCatalog={vi.fn()}
      onOpenOperations={vi.fn()}
      onOpenSafety={vi.fn()}
      onOpenSetup={vi.fn()}
      onResult={vi.fn()}
    />
  );
}

describe("AdvancedControlPlanePanel", () => {
  it("renders the live control plane directly in pro mode", () => {
    renderPanel();

    expect(screen.getByText("Live control plane")).toBeInTheDocument();
    expect(screen.getByTestId("health-panel")).toBeInTheDocument();
    expect(screen.getByTestId("domain-panel")).toHaveTextContent("Authentication:");
    expect(screen.getByTestId("activity-panel")).toHaveTextContent("Authentication:Token and API key control");
  });

  it("keeps guided actions visible without hiding raw domains in beginner mode", () => {
    renderPanel({ operatorMode: "beginner" });

    expect(screen.getByText("Guided control plane")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Open Models" })).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: "Open Safety Center" })).toHaveLength(2);
    expect(screen.getByTestId("domain-panel")).toHaveTextContent("Authentication:");
  });

  it("filters domains and routes selection through the shared callback", async () => {
    const user = userEvent.setup();
    const onSelectedDomainChange = vi.fn();

    render(
      <AdvancedControlPlanePanel
        domains={domains}
        selectedDomainId="auth"
        token="jwt"
        apiKey=""
        activity={[]}
        operatorMode="pro"
        onOperatorModeChange={vi.fn()}
        onSelectedDomainChange={onSelectedDomainChange}
        onOpenModels={vi.fn()}
        onOpenWorkflowCatalog={vi.fn()}
        onOpenOperations={vi.fn()}
        onOpenSafety={vi.fn()}
        onOpenSetup={vi.fn()}
        onResult={vi.fn()}
      />
    );

    await user.type(screen.getByPlaceholderText("agents, workflows, memory, reviews..."), "memory");
    expect(screen.getByRole("button", { name: /Memory/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Authentication/ })).not.toBeInTheDocument();
    expect(screen.getByTestId("domain-panel")).toHaveTextContent("Memory:memory");

    await user.click(screen.getByRole("button", { name: /Memory/ }));
    expect(onSelectedDomainChange).toHaveBeenCalledWith("memory");
    expect(screen.getByTestId("domain-panel")).toHaveTextContent("Memory:memory");
  });

  it("toggles between guided and direct copy using the shared operator callback", async () => {
    const user = userEvent.setup();
    const onOperatorModeChange = vi.fn();

    render(
      <AdvancedControlPlanePanel
        domains={domains}
        selectedDomainId="auth"
        token="jwt"
        apiKey=""
        activity={[]}
        operatorMode="pro"
        onOperatorModeChange={onOperatorModeChange}
        onSelectedDomainChange={vi.fn()}
        onOpenModels={vi.fn()}
        onOpenWorkflowCatalog={vi.fn()}
        onOpenOperations={vi.fn()}
        onOpenSafety={vi.fn()}
        onOpenSetup={vi.fn()}
        onResult={vi.fn()}
      />
    );

    await user.click(screen.getByRole("button", { name: "Prioritize guided routes" }));
    expect(onOperatorModeChange).toHaveBeenCalledWith("beginner");
  });

  it("routes hero buttons through the shared navigation callbacks", async () => {
    const user = userEvent.setup();
    const onOpenModels = vi.fn();
    const onOpenWorkflowCatalog = vi.fn();
    const onOpenOperations = vi.fn();
    const onOpenSafety = vi.fn();
    const onOpenSetup = vi.fn();

    render(
      <AdvancedControlPlanePanel
        domains={domains}
        selectedDomainId="auth"
        token="jwt"
        apiKey=""
        activity={[]}
        operatorMode="pro"
        onOperatorModeChange={vi.fn()}
        onSelectedDomainChange={vi.fn()}
        onOpenModels={onOpenModels}
        onOpenWorkflowCatalog={onOpenWorkflowCatalog}
        onOpenOperations={onOpenOperations}
        onOpenSafety={onOpenSafety}
        onOpenSetup={onOpenSetup}
        onResult={vi.fn()}
      />
    );

    await user.click(screen.getByRole("button", { name: "Open Models" }));
    await user.click(screen.getByRole("button", { name: "Browse workflows" }));
    await user.click(screen.getByRole("button", { name: "Open Sessions & Runs" }));
    await user.click(screen.getByRole("button", { name: "Open Safety Center" }));
    await user.click(screen.getByRole("button", { name: "Open Integrations" }));

    expect(onOpenModels).toHaveBeenCalledTimes(1);
    expect(onOpenWorkflowCatalog).toHaveBeenCalledTimes(1);
    expect(onOpenOperations).toHaveBeenCalledTimes(1);
    expect(onOpenSafety).toHaveBeenCalledTimes(1);
    expect(onOpenSetup).toHaveBeenCalledTimes(1);
  });

  it("shows an empty state when no technical domains are registered", () => {
    render(
      <AdvancedControlPlanePanel
        domains={[]}
        selectedDomainId="missing"
        token="jwt"
        apiKey=""
        activity={[]}
        operatorMode="pro"
        onOperatorModeChange={vi.fn()}
        onSelectedDomainChange={vi.fn()}
        onOpenModels={vi.fn()}
        onOpenWorkflowCatalog={vi.fn()}
        onOpenOperations={vi.fn()}
        onOpenSafety={vi.fn()}
        onOpenSetup={vi.fn()}
        onResult={vi.fn()}
      />
    );

    expect(screen.getByText("No technical domains are registered.")).toBeInTheDocument();
  });

  it("can suppress the embedded activity rail when the shell provides a global one", () => {
    render(
      <AdvancedControlPlanePanel
        domains={domains}
        selectedDomainId="auth"
        token="jwt"
        apiKey=""
        activity={[]}
        operatorMode="pro"
        showActivityRail={false}
        onOperatorModeChange={vi.fn()}
        onSelectedDomainChange={vi.fn()}
        onOpenModels={vi.fn()}
        onOpenWorkflowCatalog={vi.fn()}
        onOpenOperations={vi.fn()}
        onOpenSafety={vi.fn()}
        onOpenSetup={vi.fn()}
        onResult={vi.fn()}
      />
    );

    expect(screen.queryByTestId("activity-panel")).not.toBeInTheDocument();
  });
});
