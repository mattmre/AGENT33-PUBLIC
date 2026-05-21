import { describe, expect, it } from "vitest";

import {
  buildDeclineIntakePayload,
  decliningTrends,
  filterTrends,
  metricLabel,
  sparklinePoints
} from "./helpers";
import type { OutcomeTrend } from "./types";

describe("outcomes dashboard helpers", () => {
  const trend: OutcomeTrend = {
    metric_type: "success_rate",
    domain: "reviews",
    window: 20,
    direction: "declining",
    sample_size: 6,
    values: [0.91, 0.9, 0.88, 0.86, 0.81, 0.78],
    previous_avg: 0.9,
    current_avg: 0.816
  };

  it("formats metric labels", () => {
    expect(metricLabel("latency_ms")).toBe("Latency (ms)");
    expect(metricLabel("cost_usd")).toBe("Cost (USD)");
  });

  it("filters trends by metric", () => {
    const results = filterTrends([trend], "success_rate");
    expect(results).toHaveLength(1);
    expect(filterTrends([trend], "latency_ms")).toHaveLength(0);
  });

  it("detects declining trends", () => {
    const stableTrend = { ...trend, direction: "stable" as const };
    expect(decliningTrends([trend, stableTrend])).toHaveLength(1);
  });

  it("builds sparkline points", () => {
    const points = sparklinePoints([1, 2, 3], 100, 20);
    expect(points).toContain("0.00,20.00");
    expect(points).toContain("100.00,0.00");
  });

  it("builds decline improvement intake payload", () => {
    const payload = buildDeclineIntakePayload(trend, "reviews", "qa@example.com");
    expect(payload.title).toContain("Investigate declining Success Rate");
    expect(payload.source).toBe("outcomes-dashboard:decline-trigger");
    expect(payload.affected_phases).toEqual([30]);
  });
});
