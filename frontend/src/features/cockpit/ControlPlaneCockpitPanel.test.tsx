import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { DomainConfig } from "../../types";
import { getWorkspaceSession } from "../../data/workspaces";
import { ControlPlaneCockpitPanel } from "./ControlPlaneCockpitPanel";

vi.mock("../../components/CockpitProjectDashboard", () => ({
  CockpitProjectDashboard: () => <div data-testid="cockpit-project-dashboard">Dashboard</div>
}));

vi.mock("../../components/HealthPanel", () => ({
  HealthPanel: () => <div data-testid="health-panel">Health</div>
}));

vi.mock("../../components/DomainPanel", () => ({
  DomainPanel: ({ domain }: { domain: DomainConfig }) => <div data-testid="domain-panel">{domain.title}</div>
}));

const domains: DomainConfig[] = [
  {
    id: "agents",
    title: "Agent endpoints",
    description: "Invoke and configure runtime agents.",
    operations: [
      {
        id: "agent-list",
        title: "List agents",
        method: "GET",
        path: "/v1/agents",
        description: "List agents"
      }
    ]
  },
  {
    id: "workflows",
    title: "Workflow endpoints",
    description: "Start and inspect workflows.",
    operations: [
      {
        id: "workflow-list",
        title: "List workflows",
        method: "GET",
        path: "/v1/workflows",
        description: "List workflows"
      }
    ]
  }
];

describe("ControlPlaneCockpitPanel", () => {
  it("renders the summary dashboard, health row, and selected API surface", () => {
    render(
      <ControlPlaneCockpitPanel
        workspace={getWorkspaceSession("shipyard")}
        permissionModeId="pr-first"
        domains={domains}
        selectedDomainId="agents"
        token="jwt"
        apiKey=""
        onSelectedDomainChange={vi.fn()}
        onOpenOperations={vi.fn()}
        onOpenWorkflowStarter={vi.fn()}
        onOpenSafety={vi.fn()}
        onOpenSetup={vi.fn()}
        onResult={vi.fn()}
      />
    );

    expect(screen.getByRole("region", { name: "Operations cockpit" })).toBeInTheDocument();
    expect(screen.getByTestId("cockpit-project-dashboard")).toBeInTheDocument();
    expect(screen.getByTestId("health-panel")).toBeInTheDocument();
    expect(screen.getByTestId("domain-panel")).toHaveTextContent("Agent endpoints");
    expect(screen.getByRole("tab", { name: /Agent endpoints/i })).toHaveAttribute("aria-selected", "true");
  });

  it("routes cockpit domain changes and quick actions through callbacks", async () => {
    const user = userEvent.setup();
    const onSelectedDomainChange = vi.fn();
    const onOpenOperations = vi.fn();
    const onOpenWorkflowStarter = vi.fn();
    const onOpenSafety = vi.fn();
    const onOpenSetup = vi.fn();

    render(
      <ControlPlaneCockpitPanel
        workspace={getWorkspaceSession("shipyard")}
        permissionModeId="pr-first"
        domains={domains}
        selectedDomainId="agents"
        token="jwt"
        apiKey=""
        onSelectedDomainChange={onSelectedDomainChange}
        onOpenOperations={onOpenOperations}
        onOpenWorkflowStarter={onOpenWorkflowStarter}
        onOpenSafety={onOpenSafety}
        onOpenSetup={onOpenSetup}
        onResult={vi.fn()}
      />
    );

    await user.click(screen.getByRole("tab", { name: /Workflow endpoints/i }));
    await user.click(screen.getByRole("button", { name: "Review board" }));
    await user.click(screen.getByRole("button", { name: "Browse starters" }));
    await user.click(screen.getByRole("button", { name: "Review gates" }));
    await user.click(screen.getByRole("button", { name: "Integrations" }));

    expect(onSelectedDomainChange).toHaveBeenCalledWith("workflows");
    expect(onOpenOperations).toHaveBeenCalledTimes(1);
    expect(onOpenWorkflowStarter).toHaveBeenCalledTimes(1);
    expect(onOpenSafety).toHaveBeenCalledTimes(1);
    expect(onOpenSetup).toHaveBeenCalledTimes(1);
  });
});
