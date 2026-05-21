import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AppNavigation } from "./AppNavigation";

describe("AppNavigation", () => {
  it("renders grouped workspace navigation with the active page marked", () => {
    render(<AppNavigation activeTab="guide" onNavigate={vi.fn()} />);

    expect(screen.getByRole("navigation", { name: "Main navigation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Guide \/ Intake/ })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: /Sessions & Runs/ })).not.toHaveAttribute("aria-current");
    expect(screen.getByText("Launch")).toBeInTheDocument();
    expect(screen.getByText("Admin")).toBeInTheDocument();
  });

  it("routes selected tabs through the shared navigation callback", async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();

    render(<AppNavigation activeTab="guide" onNavigate={onNavigate} />);

    await user.click(screen.getByRole("button", { name: /Sessions & Runs/ }));

    expect(onNavigate).toHaveBeenCalledWith("operations");
  });

  it("keeps specialized tools reachable through grouped sidebar sections", async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();

    render(<AppNavigation activeTab="fabric" onNavigate={onNavigate} />);

    expect(screen.getByText("Build")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Tool Fabric/ })).toHaveAttribute("aria-current", "page");
    await user.click(screen.getByRole("button", { name: /Task group Admin/ }));

    await user.click(screen.getByRole("button", { name: /MCP Health/ }));

    expect(onNavigate).toHaveBeenCalledWith("mcp");
  });

  it("shows group descriptions so the sidebar reads like an information architecture instead of a tab wall", () => {
    render(<AppNavigation activeTab="guide" onNavigate={vi.fn()} />);

    expect(
      screen.getByText("Prepare models, integrations, and credentials before you launch work.")
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Inspect external tool fabric health and use the quarantined raw controls only when needed."
      )
    ).toBeInTheDocument();
  });
});
