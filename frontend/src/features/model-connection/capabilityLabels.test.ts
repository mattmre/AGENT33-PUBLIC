import { describe, expect, it } from "vitest";

import { getModelCapabilityTags } from "./capabilityLabels";

describe("model capability labels", () => {
  it("labels coding, free, local, and long-context models", () => {
    const tags = getModelCapabilityTags({
      id: "ollama/qwen2.5-coder:7b",
      name: "Qwen2.5 Coder 7B",
      capabilities: ["code", "local"],
      contextLength: 131_072,
      isFree: true
    }).map((tag) => tag.label);

    expect(tags).toContain("Best for coding");
    expect(tags).toContain("Free option");
    expect(tags).toContain("Long context");
  });

  it("keeps labels unique and capped for compact model cards", () => {
    const tags = getModelCapabilityTags({
      id: "openrouter/qwen/qwen3-coder-flash",
      name: "Qwen Coder Flash",
      description: "Fast coding model",
      capabilities: ["code", "fast", "coder"],
      contextLength: 200_000,
      isFree: false
    });

    expect(tags.length).toBeLessThanOrEqual(3);
    expect(new Set(tags.map((tag) => tag.label)).size).toBe(tags.length);
  });
});
