import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SafetyGateIndicator } from "./SafetyGateIndicator";
import { buildCockpitOpsSafetySnapshot } from "../data/cockpitOpsSafety";

describe("SafetyGateIndicator", () => {
  it("summarizes permission mode gates with beginner-readable counts", () => {
    const snapshot = buildCockpitOpsSafetySnapshot({ workspaceId: "solo-builder", permissionModeId: "ask" });

    render(<SafetyGateIndicator permissionModeId="ask" opsSafetyRecords={snapshot.records} />);

    expect(screen.getByRole("region", { name: "Safety gate summary" })).toHaveClass(
      "safety-gate-indicator-guided"
    );
    expect(screen.getByText("Ask before action")).toBeInTheDocument();
    expect(screen.getByLabelText("Needs review: 1")).toBeInTheDocument();
    expect(screen.queryByLabelText("Blocked: 0")).not.toBeInTheDocument();
  });

  it("shows locked modes as blocked gates", () => {
    const snapshot = buildCockpitOpsSafetySnapshot({ workspaceId: "solo-builder", permissionModeId: "restricted" });

    render(<SafetyGateIndicator permissionModeId="restricted" opsSafetyRecords={snapshot.records} isCompact />);

    expect(screen.getByRole("region", { name: "Safety gate summary" })).toHaveClass(
      "safety-gate-indicator-locked"
    );
    expect(screen.getByText("Restricted / high-risk locked")).toBeInTheDocument();
    expect(screen.getByLabelText("Blocked: 1")).toBeInTheDocument();
    expect(screen.queryByLabelText("Needs review: 0")).not.toBeInTheDocument();
  });
});
