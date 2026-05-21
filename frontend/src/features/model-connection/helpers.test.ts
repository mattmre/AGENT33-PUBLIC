import { describe, expect, it } from "vitest";

import {
  DEFAULT_LOCAL_RUNTIME_BASELINE,
  DEFAULT_MODEL_CONNECTION_BASELINE,
  buildLocalRuntimeConfigChanges,
  buildModelConnectionConfigChanges,
  buildOpenRouterConfigChanges,
  buildOpenRouterProbePayload,
  formatLocalRuntimeModelRef,
  formatLmStudioModelRef,
  formatOllamaModelRef,
  getModelReadinessLabel,
  normalizeLocalRuntimeBaseUrl,
  normalizeLmStudioBaseUrl,
  normalizeOllamaBaseUrl,
  stripLocalRuntimeModelRef,
  stripLmStudioModelRef,
  stripOllamaModelRef,
  type ModelConnectionForm
} from "./helpers";

function form(overrides: Partial<ModelConnectionForm> = {}): ModelConnectionForm {
  return {
    ...DEFAULT_MODEL_CONNECTION_BASELINE,
    apiKey: "",
    writeToEnvFile: true,
    removeStoredKey: false,
    ...overrides
  };
}

describe("model connection helpers", () => {
  it("builds only changed OpenRouter config values", () => {
    const changes = buildOpenRouterConfigChanges(
      form({ defaultModel: "qwen/qwen3-32b", apiKey: "sk-test" }),
      DEFAULT_MODEL_CONNECTION_BASELINE
    );

    expect(changes.default_model).toBe("openrouter/qwen/qwen3-32b");
    expect(changes.openrouter_api_key).toBe("sk-test");
    expect(changes.openrouter_base_url).toBeUndefined();
  });

  it("builds a probe payload with normalized model and transient key", () => {
    const payload = buildOpenRouterProbePayload(form({ defaultModel: "qwen/qwen3-32b", apiKey: "sk-test" }));

    expect(payload.default_model).toBe("openrouter/qwen/qwen3-32b");
    expect(payload.openrouter_api_key).toBe("sk-test");
    expect(payload.openrouter_base_url).toBe(DEFAULT_MODEL_CONNECTION_BASELINE.baseUrl);
  });

  it("normalizes native Ollama URLs without touching OpenAI-compatible providers", () => {
    expect(normalizeOllamaBaseUrl("http://localhost:11434/v1")).toBe("http://localhost:11434");
    expect(normalizeOllamaBaseUrl("http://localhost:11434/")).toBe("http://localhost:11434");
    expect(formatOllamaModelRef("qwen2.5-coder:7b")).toBe("ollama/qwen2.5-coder:7b");
    expect(stripOllamaModelRef("ollama/qwen2.5-coder:7b")).toBe("qwen2.5-coder:7b");
  });

  it("preserves LM Studio as an OpenAI-compatible /v1 endpoint", () => {
    expect(normalizeLmStudioBaseUrl("http://localhost:1234")).toBe("http://localhost:1234/v1");
    expect(normalizeLmStudioBaseUrl("http://localhost:1234/v1")).toBe("http://localhost:1234/v1");
    expect(normalizeLmStudioBaseUrl("http://localhost:1234/v1/")).toBe("http://localhost:1234/v1");
    expect(formatLmStudioModelRef("qwen2.5-coder-7b-instruct")).toBe(
      "lmstudio/qwen2.5-coder-7b-instruct"
    );
    expect(stripLmStudioModelRef("lmstudio/qwen2.5-coder-7b-instruct")).toBe(
      "qwen2.5-coder-7b-instruct"
    );
  });

  it("normalizes the startup runtime endpoint and config changes", () => {
    expect(normalizeLocalRuntimeBaseUrl("http://localhost:8033", "vLLM")).toBe(
      "http://localhost:8033/v1"
    );
    expect(normalizeLocalRuntimeBaseUrl("http://localhost:8033/v1/", "vLLM")).toBe(
      "http://localhost:8033/v1"
    );
    expect(formatLocalRuntimeModelRef("qwen3-coder-next", "vLLM")).toBe(
      "llamacpp/qwen3-coder-next"
    );
    expect(stripLocalRuntimeModelRef("llamacpp/qwen3-coder-next")).toBe("qwen3-coder-next");

    const changes = buildLocalRuntimeConfigChanges(
      form({
        defaultModel: "llamacpp/qwen3-coder-next",
        baseUrl: "http://localhost:8033",
        localEngine: "vLLM"
      }),
      DEFAULT_MODEL_CONNECTION_BASELINE,
      DEFAULT_LOCAL_RUNTIME_BASELINE
    );

    expect(changes.default_model).toBe("llamacpp/qwen3-coder-next");
    expect(changes.local_orchestration_base_url).toBe("http://localhost:8033/v1");
    expect(changes.local_orchestration_engine).toBe("vLLM");
  });

  it("maps the startup runtime onto Ollama settings when the local engine is Ollama", () => {
    expect(normalizeLocalRuntimeBaseUrl("http://localhost:11434/v1", "ollama")).toBe(
      "http://localhost:11434"
    );
    expect(formatLocalRuntimeModelRef("qwen3-coder", "ollama")).toBe("ollama/qwen3-coder");
    expect(stripLocalRuntimeModelRef("ollama/qwen3-coder")).toBe("qwen3-coder");

    const changes = buildLocalRuntimeConfigChanges(
      form({
        defaultModel: "ollama/qwen3-coder",
        baseUrl: "http://localhost:11434/v1",
        localEngine: "ollama"
      }),
      DEFAULT_MODEL_CONNECTION_BASELINE,
      DEFAULT_LOCAL_RUNTIME_BASELINE
    );

    expect(changes.default_model).toBe("ollama/qwen3-coder");
    expect(changes.ollama_base_url).toBe("http://localhost:11434");
    expect(changes.ollama_default_model).toBe("qwen3-coder");
    expect(changes.local_orchestration_model).toBe("qwen3-coder");
    expect(changes.local_orchestration_engine).toBe("ollama");
  });

  it("routes config changes through the selected preset path", () => {
    const openRouterChanges = buildModelConnectionConfigChanges(
      "openrouter",
      form({ defaultModel: "qwen/qwen3-32b" }),
      DEFAULT_MODEL_CONNECTION_BASELINE,
      DEFAULT_LOCAL_RUNTIME_BASELINE
    );
    const localRuntimeChanges = buildModelConnectionConfigChanges(
      "local-runtime",
      form({ defaultModel: "llamacpp/qwen3-coder-next", localEngine: "llama.cpp" }),
      DEFAULT_MODEL_CONNECTION_BASELINE,
      DEFAULT_LOCAL_RUNTIME_BASELINE
    );

    expect(openRouterChanges.default_model).toBe("openrouter/qwen/qwen3-32b");
    expect(localRuntimeChanges.default_model).toBe("llamacpp/qwen3-coder-next");
    expect(localRuntimeChanges.local_orchestration_model).toBeUndefined();
  });

  it("summarizes model readiness in user-facing states", () => {
    expect(getModelReadinessLabel(false, false, "", false)).toBe("Connect engine access");
    expect(getModelReadinessLabel(true, false, "", false)).toBe("Add provider key");
    expect(getModelReadinessLabel(true, true, "", false)).toBe("Choose a model");
    expect(getModelReadinessLabel(true, true, "openrouter/qwen/qwen3-32b", true)).toBe(
      "Ready for workflows"
    );
  });
});
