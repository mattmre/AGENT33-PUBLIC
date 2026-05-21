import { describe, expect, it } from "vitest";

import { buildResourceManifest } from "./resourceManifest";
import type { FabricPlan } from "./types";

const PLAN: FabricPlan = {
  objective: "research competitors",
  tools: [
    {
      name: "web_search",
      description: "Search the web",
      score: 0.91,
      status: "active",
      version: "1.0.0",
      tags: ["research"]
    }
  ],
  skills: [
    {
      name: "competitive-research",
      description: "Compare projects",
      score: 0.68,
      version: "1.0.0",
      tags: ["research"],
      pack: null
    }
  ],
  workflows: [
    {
      name: "research-loop",
      description: "Research and synthesize",
      score: 0.82,
      source: "template",
      version: "1.0.0",
      tags: ["workflow"],
      source_path: "core/workflows/research-loop.yaml",
      pack: null
    }
  ]
};

describe("resource manifest", () => {
  it("summarizes trust, compatibility, and evidence receipts for resolved assets", () => {
    const manifest = buildResourceManifest(PLAN);

    expect(manifest.summary).toBe("2 ready resources, 1 requiring review.");
    expect(manifest.items.map((item) => item.id)).toEqual([
      "tool:web_search",
      "skill:competitive-research",
      "workflow:template:research-loop"
    ]);
    expect(manifest.items[0]).toMatchObject({
      status: "ready",
      trustSummary: "Callable tool is active in discovery."
    });
    expect(manifest.items[1]).toMatchObject({
      status: "needs-review",
      trustSummary: "Skill is runtime-local or unpacked."
    });
    expect(manifest.items.every((item) => item.evidenceReceipt.includes("run ledger proof"))).toBe(true);
  });

  it("keeps an empty manifest explicit before resolution", () => {
    const manifest = buildResourceManifest({ objective: "", tools: [], skills: [], workflows: [] });

    expect(manifest.items).toEqual([]);
    expect(manifest.summary).toContain("No resource manifest yet");
  });
});
