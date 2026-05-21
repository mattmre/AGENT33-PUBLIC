import { describe, expect, it } from "vitest";

import {
  DEFAULT_PERMISSION_MODE_ID,
  PERMISSION_MODES,
  PERMISSION_MODE_IDS,
  getPermissionMode,
  isPermissionModeId
} from "./permissionModes";

describe("permission mode data", () => {
  it("defines beginner-readable labels for every permission mode id", () => {
    expect(PERMISSION_MODES.map((mode) => mode.id).sort()).toEqual([...PERMISSION_MODE_IDS].sort());

    for (const mode of PERMISSION_MODES) {
      expect(mode.label).not.toMatch(/json|endpoint|payload/i);
      expect(mode.headline.length).toBeGreaterThan(10);
      expect(mode.allowedNow.length).toBeGreaterThan(10);
      expect(mode.reviewGate.length).toBeGreaterThan(10);
    }
  });

  it("uses ask-before-action as the safe default", () => {
    expect(DEFAULT_PERMISSION_MODE_ID).toBe("ask");
    expect(getPermissionMode(DEFAULT_PERMISSION_MODE_ID).label).toBe("Ask before action");
  });

  it("guards persisted ids before using them", () => {
    expect(isPermissionModeId("pr-first")).toBe(true);
    expect(isPermissionModeId("raw-admin")).toBe(false);
    expect(isPermissionModeId(null)).toBe(false);
  });
});
