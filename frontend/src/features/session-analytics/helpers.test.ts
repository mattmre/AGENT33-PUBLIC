import { describe, expect, it } from "vitest";

import { buildSparklinePoints, formatCost, formatDuration, formatTokens } from "./helpers";
import type { DailyActivity } from "./types";

describe("session analytics helpers", () => {
  describe("formatCost", () => {
    it("formats zero cost", () => {
      expect(formatCost(0)).toBe("$0.00");
    });

    it("formats fractional cost", () => {
      expect(formatCost(1.234)).toBe("$1.23");
    });

    it("formats whole dollar cost", () => {
      expect(formatCost(42)).toBe("$42.00");
    });

    it("formats small cost with trailing zeros", () => {
      expect(formatCost(0.1)).toBe("$0.10");
    });
  });

  describe("formatTokens", () => {
    it("formats small counts as plain numbers", () => {
      expect(formatTokens(0)).toBe("0");
      expect(formatTokens(500)).toBe("500");
      expect(formatTokens(999)).toBe("999");
    });

    it("formats thousands with K suffix", () => {
      expect(formatTokens(1000)).toBe("1.0K");
      expect(formatTokens(1200)).toBe("1.2K");
      expect(formatTokens(45600)).toBe("45.6K");
    });

    it("formats millions with M suffix", () => {
      expect(formatTokens(1000000)).toBe("1.0M");
      expect(formatTokens(45600000)).toBe("45.6M");
    });

    it("formats billions with B suffix", () => {
      expect(formatTokens(1000000000)).toBe("1.0B");
      expect(formatTokens(2500000000)).toBe("2.5B");
    });
  });

  describe("formatDuration", () => {
    it("formats seconds only", () => {
      expect(formatDuration(45)).toBe("45s");
    });

    it("formats minutes and seconds", () => {
      expect(formatDuration(150)).toBe("2m 30s");
    });

    it("formats exact minutes without seconds", () => {
      expect(formatDuration(120)).toBe("2m");
    });

    it("formats zero seconds", () => {
      expect(formatDuration(0)).toBe("0s");
    });

    it("rounds fractional seconds", () => {
      expect(formatDuration(5.7)).toBe("6s");
    });
  });

  describe("buildSparklinePoints", () => {
    it("returns empty string for no data", () => {
      expect(buildSparklinePoints([], 200, 60)).toBe("");
    });

    it("produces valid SVG points for single data point", () => {
      const data: DailyActivity[] = [
        { date: "2026-03-01", sessions: 5, tokens: 100, cost_usd: 0.5 },
      ];
      const points = buildSparklinePoints(data, 200, 60);
      // Single point: x=0, range=0 defaults to 1, y = 60 - ((100-100)/1)*60 = 60
      expect(points).toBe("0.00,60.00");
    });

    it("produces valid SVG points for multiple data points", () => {
      const data: DailyActivity[] = [
        { date: "2026-03-01", sessions: 5, tokens: 100, cost_usd: 0.5 },
        { date: "2026-03-02", sessions: 8, tokens: 200, cost_usd: 1.0 },
        { date: "2026-03-03", sessions: 3, tokens: 50, cost_usd: 0.2 },
      ];
      const points = buildSparklinePoints(data, 200, 60);
      // First point: x=0, tokens=100 -> y = 60 - ((100-50)/150)*60 = 60-20=40
      // Last point: x=200, tokens=50 (min) -> y = 60 - 0 = 60
      expect(points).toContain("0.00,");
      expect(points).toContain("200.00,60.00");
      // Middle point: x=100, tokens=200 (max) -> y = 60 - 60 = 0
      expect(points).toContain("100.00,0.00");
    });

    it("handles flat data where all values are equal", () => {
      const data: DailyActivity[] = [
        { date: "2026-03-01", sessions: 1, tokens: 50, cost_usd: 0.1 },
        { date: "2026-03-02", sessions: 1, tokens: 50, cost_usd: 0.1 },
      ];
      const points = buildSparklinePoints(data, 200, 60);
      // When range is 0, defaults to 1, so y = 60 - 0 = 60 for both
      expect(points).toBe("0.00,60.00 200.00,60.00");
    });
  });
});
