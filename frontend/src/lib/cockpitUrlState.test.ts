import { describe, expect, it } from "vitest";

import {
  createCockpitUrl,
  isArtifactDrawerSectionId,
  readCockpitUrlState
} from "./cockpitUrlState";

describe("cockpit URL state", () => {
  it("reads valid cockpit deep-link params", () => {
    expect(
      readCockpitUrlState("?view=operations&workspace=shipyard&permission=pr-first&drawer=tests&operatorMode=beginner")
    ).toEqual({
      activeTab: "operations",
      workspaceId: "shipyard",
      permissionModeId: "pr-first",
      drawerSectionId: "tests",
      operatorMode: "beginner"
    });
  });

  it("falls back safely for invalid deep-link params", () => {
    expect(
      readCockpitUrlState("?view=not-real&workspace=nope&permission=god-mode&drawer=terminal", {
        activeTab: "guide",
        workspaceId: "test-review",
        permissionModeId: "workspace",
        drawerSectionId: "activity",
        operatorMode: "pro"
      })
    ).toEqual({
      activeTab: "guide",
      workspaceId: "test-review",
      permissionModeId: "workspace",
      drawerSectionId: "activity",
      operatorMode: "pro"
    });
  });

  it("falls back safely for invalid operator mode params", () => {
    expect(
      readCockpitUrlState("?operatorMode=autopilot", {
        operatorMode: "beginner"
      }).operatorMode
    ).toBe("beginner");
  });

  it("migrates legacy tab params when view is absent or invalid", () => {
    expect(readCockpitUrlState("?tab=design-kit").activeTab).toBe("design-kit");
    expect(readCockpitUrlState("?view=nope&tab=safety").activeTab).toBe("safety");
    expect(readCockpitUrlState("?view=operations&tab=safety").activeTab).toBe("operations");
  });

  it("migrates legacy grouped tab and subtab params", () => {
    expect(readCockpitUrlState("?tab=operate&sub=operations").activeTab).toBe("operations");
    expect(readCockpitUrlState("?tab=admin&sub=design-kit").activeTab).toBe("design-kit");
    expect(readCockpitUrlState("?tab=admin&sub=nope").activeTab).toBe("mcp");
    expect(readCockpitUrlState("?view=nope&tab=build&sub=builder").activeTab).toBe("builder");
    expect(readCockpitUrlState("?view=advanced&tab=admin&sub=design-kit").activeTab).toBe("advanced");
  });

  it("creates shareable cockpit URLs and only keeps drawer state for operations", () => {
    expect(
      createCockpitUrl("http://localhost:5173/?foo=bar&tab=advanced&sub=raw#main", {
        activeTab: "operations",
        workspaceId: "research-build",
        permissionModeId: "ask",
        drawerSectionId: "commands",
        operatorMode: "beginner"
      })
    ).toBe("/?foo=bar&view=operations&workspace=research-build&permission=ask&operatorMode=beginner&drawer=commands#main");

    expect(
      createCockpitUrl("http://localhost:5173/?drawer=logs", {
        activeTab: "guide",
        workspaceId: "solo-builder",
        permissionModeId: "observe",
        drawerSectionId: "logs",
        operatorMode: "pro"
      })
    ).toBe("/?view=guide&workspace=solo-builder&permission=observe&operatorMode=pro");
  });

  it("validates artifact drawer section ids", () => {
    expect(isArtifactDrawerSectionId("outcome")).toBe(true);
    expect(isArtifactDrawerSectionId("terminal")).toBe(false);
    expect(isArtifactDrawerSectionId(null)).toBe(false);
  });
});
