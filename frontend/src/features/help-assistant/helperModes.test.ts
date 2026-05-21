import { describe, expect, it } from "vitest";

import {
  HELPER_RUNTIME_MODES,
  getHelperRuntimeMode,
  getRuntimeStatusLabel
} from "./helperModes";

describe("helper runtime modes", () => {
  it("keeps static cited search as the available default", () => {
    expect(HELPER_RUNTIME_MODES[0].id).toBe("static-search");
    expect(HELPER_RUNTIME_MODES[0].status).toBe("available");
    expect(HELPER_RUNTIME_MODES[0].setup).toContain("No setup required");
  });

  it("falls back to static search for unknown mode ids", () => {
    expect(getHelperRuntimeMode("missing").id).toBe("static-search");
  });

  it("labels runtime readiness in beginner language", () => {
    expect(getRuntimeStatusLabel("available")).toBe("Available now");
    expect(getRuntimeStatusLabel("pilot-ready")).toBe("Pilot path");
    expect(getRuntimeStatusLabel("requires-setup")).toBe("Needs local setup");
  });
});
