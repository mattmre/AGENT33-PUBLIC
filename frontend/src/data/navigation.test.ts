import { describe, expect, it } from "vitest";

import { HELP_ASSISTANT_TARGETS } from "../features/help-assistant/types";
import {
  APP_PRIMARY_NAV_ITEMS,
  APP_SECONDARY_NAV_GROUPS,
  APP_TAB_GROUPS,
  APP_TAB_IDS,
  DEFAULT_APP_TAB,
  ROLE_SELECTED_DEFAULT_APP_TAB,
  getAppTabDescription,
  getAppTabGroup,
  getAppTabLabel,
  isAppTab,
  isPrimaryAppTab,
  isSecondaryAppTab
} from "./navigation";

describe("app navigation registry", () => {
  it("keeps every tab id represented exactly once in navigation groups", () => {
    const groupedTabIds = APP_TAB_GROUPS.flatMap((group) => group.tabs.map((tab) => tab.id));

    expect(new Set(groupedTabIds).size).toBe(groupedTabIds.length);
    expect(groupedTabIds).toEqual(APP_TAB_IDS);
  });

  it("keeps default destinations valid", () => {
    expect(isAppTab(DEFAULT_APP_TAB)).toBe(true);
    expect(isAppTab(ROLE_SELECTED_DEFAULT_APP_TAB)).toBe(true);
  });

  it("keeps Help Assistant targets compatible with app navigation", () => {
    expect(HELP_ASSISTANT_TARGETS.every((target) => isAppTab(target))).toBe(true);
  });

  it("returns beginner-readable labels for registered tabs", () => {
    expect(getAppTabLabel("guide")).toBe("Guide / Intake");
    expect(getAppTabLabel("operations")).toBe("Sessions & Runs");
    expect(getAppTabLabel("advanced")).toBe("Advanced");
    expect(getAppTabDescription("models")).toContain("Choose a default model");
    expect(getAppTabGroup("operations")?.label).toBe("Operate");
  });

  it("splits cockpit primary navigation from demoted tools without losing destinations", () => {
    const primaryIds = APP_PRIMARY_NAV_ITEMS.map((item) => item.id);
    const secondaryIds = APP_SECONDARY_NAV_GROUPS.flatMap((group) => group.tabs.map((tab) => tab.id));
    const splitIds = [...primaryIds, ...secondaryIds];

    expect(new Set(primaryIds).size).toBe(primaryIds.length);
    expect(new Set(secondaryIds).size).toBe(secondaryIds.length);
    expect(primaryIds.some((id) => secondaryIds.includes(id))).toBe(false);
    expect(new Set(splitIds)).toEqual(new Set(APP_TAB_IDS));
    expect(primaryIds).toEqual(["guide", "start", "operations", "starter", "models", "safety"]);
  });

  it("identifies whether a tab is a primary cockpit destination or a secondary tool", () => {
    expect(isPrimaryAppTab("operations")).toBe(true);
    expect(isSecondaryAppTab("operations")).toBe(false);
    expect(isPrimaryAppTab("fabric")).toBe(false);
    expect(isSecondaryAppTab("fabric")).toBe(true);
  });
});
