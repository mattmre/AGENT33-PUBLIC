import { describe, expect, it } from "vitest";

import { modulesDomain } from "./modules";

describe("modulesDomain", () => {
  it("uses mounted skill matching and authoring routes", () => {
    expect(modulesDomain.operations.map((operation) => `${operation.method} ${operation.path}`)).toEqual([
      "POST /v1/skills/match",
      "GET /v1/skills/match/thresholds",
      "POST /v1/skills/authoring/drafts"
    ]);
  });

  it("does not expose the removed catch-all skills list route", () => {
    expect(modulesDomain.operations.map((operation) => operation.path)).not.toContain("/v1/skills");
  });
});
