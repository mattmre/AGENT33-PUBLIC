import { describe, expect, it } from "vitest";

import { DEFAULT_MODEL_CONNECTION_BASELINE, type ModelConnectionForm } from "./helpers";
import {
  PROVIDER_PRESETS,
  applyProviderPresetToForm,
  getProviderPreset,
  inferProviderPresetId
} from "./presets";

function form(overrides: Partial<ModelConnectionForm> = {}): ModelConnectionForm {
  return {
    ...DEFAULT_MODEL_CONNECTION_BASELINE,
    apiKey: "",
    writeToEnvFile: true,
    removeStoredKey: false,
    ...overrides
  };
}

describe("provider presets", () => {
  it("defines beginner setup paths for cloud, local, and custom providers", () => {
    expect(PROVIDER_PRESETS.map((preset) => preset.id)).toEqual([
      "openrouter",
      "local-runtime",
      "ollama",
      "lm-studio",
      "custom-openai"
    ]);
    for (const preset of PROVIDER_PRESETS) {
      expect(preset.name).toBeTruthy();
      expect(preset.description.length).toBeGreaterThan(20);
      expect(preset.recommendedModels.length).toBeGreaterThan(0);
    }
    expect(getProviderPreset("openrouter")?.baseUrlDefault).toContain("/v1");
    expect(getProviderPreset("local-runtime")?.baseUrlDefault).toContain(":8033");
    expect(getProviderPreset("ollama")?.baseUrlDefault).toBe("http://localhost:11434");
    expect(getProviderPreset("lm-studio")?.baseUrlDefault).toBe("http://localhost:1234/v1");
    expect(getProviderPreset("lm-studio")?.needsApiKey).toBe(false);
  });

  it("looks up and infers presets from base URLs", () => {
    expect(getProviderPreset("ollama")?.name).toBe("Ollama");
    expect(getProviderPreset("missing")).toBeNull();
    expect(inferProviderPresetId("http://localhost:11434/v1")).toBe("ollama");
    expect(inferProviderPresetId("http://host.docker.internal:11434")).toBe("ollama");
    expect(inferProviderPresetId("http://localhost:1234/v1")).toBe("lm-studio");
    expect(inferProviderPresetId("http://host.docker.internal:1234/v1")).toBe("lm-studio");
    expect(inferProviderPresetId("http://localhost:8033/v1")).toBe("local-runtime");
    expect(
      inferProviderPresetId("https://runtime.internal.example/v1", {
        localRuntimeBaseUrl: "https://runtime.internal.example/v1"
      })
    ).toBe("local-runtime");
    expect(inferProviderPresetId("https://openrouter.ai/api/v1")).toBe("openrouter");
    expect(inferProviderPresetId("https://example.com/v1")).toBe("custom-openai");
  });

  it("applies a local preset without carrying a typed cloud key into the local form", () => {
    const ollama = getProviderPreset("ollama");
    expect(ollama).not.toBeNull();

    const next = applyProviderPresetToForm(
      form({ apiKey: "sk-or-v1-secret", removeStoredKey: true }),
      ollama!
    );

    expect(next.baseUrl).toBe("http://localhost:11434");
    expect(next.defaultModel).toBe("ollama/qwen2.5-coder:7b");
    expect(next.apiKey).toBe("");
    expect(next.removeStoredKey).toBe(false);
  });

  it("applies the startup runtime preset with a local engine default", () => {
    const localRuntime = getProviderPreset("local-runtime");
    expect(localRuntime).not.toBeNull();

    const next = applyProviderPresetToForm(form(), localRuntime!);

    expect(next.baseUrl).toBe("http://host.docker.internal:8033/v1");
    expect(next.defaultModel).toBe("llamacpp/qwen3-coder-next");
    expect(next.localEngine).toBe("llama.cpp");
    expect(next.apiKey).toBe("");
  });
});
