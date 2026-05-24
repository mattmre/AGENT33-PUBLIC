import { describe, expect, it } from "vitest";

import { outcomesDomain } from "./outcomes";

describe("outcomesDomain", () => {
  it("uses mounted outcome event, trend, and dashboard routes", () => {
    expect(outcomesDomain.operations.map((operation) => `${operation.method} ${operation.path}`)).toEqual([
      "GET /v1/outcomes/trends/{metric_type}",
      "POST /v1/outcomes/events",
      "GET /v1/outcomes/dashboard"
    ]);
  });

  it("binds trend metric_type as a path parameter", () => {
    const trend = outcomesDomain.operations.find((operation) => operation.id === "outcomes-get-trend");

    expect(trend?.defaultPathParams).toEqual({ metric_type: "success_rate" });
    expect(trend?.defaultQuery).toEqual({ domain: "all", window: "20" });
  });
});
