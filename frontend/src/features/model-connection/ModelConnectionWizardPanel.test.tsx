import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiRequest } from "../../lib/api";
import { ModelConnectionWizardPanel } from "./ModelConnectionWizardPanel";

vi.mock("../../lib/api", () => ({
  apiRequest: vi.fn()
}));

const apiRequestMock = vi.mocked(apiRequest);

function mockApiRequest(): void {
  apiRequestMock.mockImplementation(({ path }) => {
    if (path === "/v1/operator/config") {
      return Promise.resolve({
        ok: true,
        status: 200,
        durationMs: 5,
        url: "http://localhost/v1/operator/config",
        data: {
          groups: {
            llm: {
              default_model: "openrouter/auto",
              openrouter_base_url: "https://openrouter.ai/api/v1"
            },
            ollama: {
              ollama_base_url: "http://localhost:11434",
              ollama_default_model: "qwen2.5-coder:7b"
            },
            lm_studio: {
              lm_studio_base_url: "http://localhost:1234/v1",
              lm_studio_default_model: "qwen2.5-coder-7b-instruct"
            },
            local_orchestration: {
              local_orchestration_base_url: "http://host.docker.internal:8033/v1",
              local_orchestration_model: "qwen3-coder-next",
              local_orchestration_engine: "vLLM"
            }
          }
        }
      });
    }
    if (path === "/v1/openrouter/models") {
      return Promise.resolve({
        ok: true,
        status: 200,
        durationMs: 5,
        url: "http://localhost/v1/openrouter/models",
        data: { data: [] }
      });
    }
    if (path === "/v1/ollama/status") {
      return Promise.resolve({
        ok: true,
        status: 200,
        durationMs: 5,
        url: "http://localhost/v1/ollama/status",
        data: {
          provider: "ollama",
          state: "available",
          ok: true,
          base_url: "http://localhost:11434",
          message: "Detected 2 local Ollama models.",
          models: [
            {
              name: "qwen2.5-coder:7b",
              size: 4_700_000_000,
              details: { parameter_size: "7B", quantization_level: "Q4_K_M" }
            },
            {
              name: "llama3.2:3b",
              size: 2_000_000_000,
              details: { parameter_size: "3B", quantization_level: "Q4_0" }
            }
          ]
        }
      });
    }
    if (path === "/v1/lm-studio/status") {
      return Promise.resolve({
        ok: true,
        status: 200,
        durationMs: 5,
        url: "http://localhost/v1/lm-studio/status",
        data: {
          provider: "lm-studio",
          state: "available",
          ok: true,
          base_url: "http://localhost:1234/v1",
          message: "Detected 2 LM Studio models.",
          models: [
            {
              id: "qwen2.5-coder-7b-instruct",
              name: "qwen2.5-coder-7b-instruct",
              owned_by: "lmstudio",
              context_length: 32_768
            },
            {
              id: "mistral-nemo-instruct",
              name: "mistral-nemo-instruct",
              owned_by: "lmstudio",
              context_length: 128_000
            }
          ]
        }
      });
    }
    if (path === "/v1/model-health") {
      return Promise.resolve({
        ok: true,
        status: 200,
        durationMs: 5,
        url: "http://localhost/v1/model-health",
        data: {
          overall_state: "ready",
          summary: "3 local runtimes ready with 5 detected models.",
          ready_provider_count: 3,
          attention_provider_count: 0,
          total_model_count: 5,
          providers: [
            {
              provider: "ollama",
              label: "Ollama",
              state: "available",
              ok: true,
              base_url: "http://localhost:11434",
              model_count: 2,
              message: "Detected 2 local Ollama models.",
              action: "Choose a detected Ollama model for local workflows."
            },
            {
              provider: "lm-studio",
              label: "LM Studio",
              state: "available",
              ok: true,
              base_url: "http://localhost:1234/v1",
              model_count: 2,
              message: "Detected 2 LM Studio models.",
              action: "Choose a detected LM Studio model for local workflows."
            },
            {
              provider: "local-orchestration",
              label: "vLLM",
              state: "available",
              ok: true,
              base_url: "http://host.docker.internal:8033/v1",
              default_model: "qwen3-coder-next",
              model_count: 1,
              message: "Detected 1 local orchestration model.",
              action: "Choose a detected vLLM model for local workflows."
            }
          ]
        }
      });
    }
    return Promise.resolve({
      ok: true,
      status: 200,
      durationMs: 5,
      url: `http://localhost${path}`,
      data: {}
    });
  });
}

function getLocalRuntimePanel(label: string): HTMLElement {
  const panel = Array.from(document.querySelectorAll(".local-runtime-panel")).find((candidate) =>
    candidate.textContent?.includes(label)
  );
  expect(panel).not.toBeNull();
  return panel as HTMLElement;
}

describe("ModelConnectionWizardPanel provider setup v2", () => {
  beforeEach(() => {
    apiRequestMock.mockReset();
    mockApiRequest();
  });

  it("renders provider paths before model settings", () => {
    render(
      <ModelConnectionWizardPanel
        token=""
        apiKey=""
        onOpenSetup={vi.fn()}
        onOpenWorkflowCatalog={vi.fn()}
        onResult={vi.fn()}
      />
    );

    expect(screen.getByRole("heading", { name: "Pick your model provider path" })).toBeInTheDocument();
    const providerPaths = within(screen.getByRole("group", { name: "Provider setup paths" }));
    expect(providerPaths.getByRole("button", { name: /OpenRouter/ })).toHaveAttribute("aria-pressed", "true");
    expect(providerPaths.getByRole("button", { name: /^Local Startup runtime/ })).toBeInTheDocument();
    expect(providerPaths.getByRole("button", { name: /^Local Ollama/ })).toBeInTheDocument();
    expect(providerPaths.getByRole("button", { name: /^Local LM Studio/ })).toBeInTheDocument();
    expect(providerPaths.getByRole("button", { name: /^Custom OpenAI-compatible/ })).toBeInTheDocument();
  });

  it("applies a local preset to the existing form fields", async () => {
    const user = userEvent.setup();
    render(
      <ModelConnectionWizardPanel
        token=""
        apiKey=""
        onOpenSetup={vi.fn()}
        onOpenWorkflowCatalog={vi.fn()}
        onResult={vi.fn()}
      />
    );

    const providerPaths = within(screen.getByRole("group", { name: "Provider setup paths" }));
    await user.click(providerPaths.getByRole("button", { name: /^Local Ollama/ }));
    expect(providerPaths.getByRole("button", { name: /^Local Ollama/ })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    expect(screen.getByLabelText("Base URL")).toHaveValue("http://localhost:11434");
    expect(screen.getByLabelText("Default model")).toHaveValue("ollama/qwen2.5-coder:7b");
    expect(screen.getByText("Local path can run without a key")).toBeInTheDocument();
  });

  it("shows detected Ollama models and lets users choose one", async () => {
    const user = userEvent.setup();
    render(
      <ModelConnectionWizardPanel
        token="operator-token"
        apiKey=""
        onOpenSetup={vi.fn()}
        onOpenWorkflowCatalog={vi.fn()}
        onResult={vi.fn()}
      />
    );

    const providerPaths = within(screen.getByRole("group", { name: "Provider setup paths" }));
    await user.click(providerPaths.getByRole("button", { name: /^Local Ollama/ }));

    const ollamaStatusPanel = getLocalRuntimePanel("Local Ollama status");
    expect(within(ollamaStatusPanel).getByText("Detected 2 local Ollama models.")).toBeInTheDocument();
    const detectedModels = within(screen.getByRole("group", { name: "Detected Ollama models" }));
    await user.click(detectedModels.getByRole("button", { name: /llama3.2:3b/ }));

    expect(screen.getByLabelText("Default model")).toHaveValue("ollama/llama3.2:3b");
    expect(apiRequestMock).toHaveBeenCalledWith(
      expect.objectContaining({
        method: "GET",
        path: "/v1/ollama/status",
        query: undefined
      })
    );
  });

  it("shows unified local model health and refreshes with edited local URLs", async () => {
    const user = userEvent.setup();
    render(
      <ModelConnectionWizardPanel
        token="operator-token"
        apiKey=""
        onOpenSetup={vi.fn()}
        onOpenWorkflowCatalog={vi.fn()}
        onResult={vi.fn()}
      />
    );

    expect(await screen.findByText("One place to see what can run now")).toBeInTheDocument();
    expect(screen.getByText("3 local runtimes ready with 5 detected models.")).toBeInTheDocument();
    const healthKpis = screen.getByLabelText("Local runtime readiness");
    expect(within(healthKpis).getByText("5")).toBeInTheDocument();
    expect(within(healthKpis).getByText("models detected")).toBeInTheDocument();

    const providerPaths = within(screen.getByRole("group", { name: "Provider setup paths" }));
    await user.click(providerPaths.getByRole("button", { name: /^Local LM Studio/ }));
    const baseUrlInput = screen.getByLabelText("Base URL");
    await user.clear(baseUrlInput);
    await user.type(baseUrlInput, "http://127.0.0.1:1234");
    await user.click(screen.getByRole("button", { name: "Refresh local health" }));

    await waitFor(() =>
      expect(apiRequestMock).toHaveBeenCalledWith(
        expect.objectContaining({
          method: "GET",
          path: "/v1/model-health",
          query: { lm_studio_base_url: "http://127.0.0.1:1234/v1" }
        })
      )
    );
  });

  it("loads the startup runtime preset from operator config and tests it through unified health", async () => {
    const user = userEvent.setup();
    render(
      <ModelConnectionWizardPanel
        token="operator-token"
        apiKey=""
        onOpenSetup={vi.fn()}
        onOpenWorkflowCatalog={vi.fn()}
        onResult={vi.fn()}
      />
    );

    const providerPaths = within(screen.getByRole("group", { name: "Provider setup paths" }));
    await user.click(providerPaths.getByRole("button", { name: /^Local Startup runtime/ }));

    expect(screen.getByLabelText("Base URL")).toHaveValue("http://host.docker.internal:8033/v1");
    expect(screen.getByLabelText("Default model")).toHaveValue("llamacpp/qwen3-coder-next");
    expect(screen.getByLabelText("Runtime engine")).toHaveValue("vLLM");
    const runtimePanel = getLocalRuntimePanel("vLLM");
    expect(within(runtimePanel).getByText("Detected 1 local orchestration model.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Test connection" }));

    expect(
      await screen.findByText(/vLLM is ready at http:\/\/host\.docker\.internal:8033\/v1/)
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(apiRequestMock).toHaveBeenCalledWith(
        expect.objectContaining({
          method: "GET",
          path: "/v1/model-health",
          query: undefined
        })
      )
    );
  });

  it("infers the startup runtime from configured local orchestration state even when the saved model is unprefixed", async () => {
    apiRequestMock.mockReset();
    apiRequestMock.mockImplementation(({ path }) => {
      if (path === "/v1/operator/config") {
        return Promise.resolve({
          ok: true,
          status: 200,
          durationMs: 5,
          url: "http://localhost/v1/operator/config",
          data: {
            groups: {
              llm: {
                default_model: "qwen3-coder-next",
                openrouter_base_url: "https://openrouter.ai/api/v1"
              },
              ollama: {},
              lm_studio: {},
              local_orchestration: {
                local_orchestration_base_url: "https://runtime.internal.example/v1",
                local_orchestration_model: "qwen3-coder-next",
                local_orchestration_engine: "vLLM"
              }
            }
          }
        });
      }
      if (path === "/v1/openrouter/models") {
        return Promise.resolve({
          ok: true,
          status: 200,
          durationMs: 5,
          url: "http://localhost/v1/openrouter/models",
          data: { data: [] }
        });
      }
      if (path === "/v1/model-health") {
        return Promise.resolve({
          ok: true,
          status: 200,
          durationMs: 5,
          url: "http://localhost/v1/model-health",
          data: {
            overall_state: "ready",
            summary: "1 local runtime ready with 1 detected model.",
            ready_provider_count: 1,
            attention_provider_count: 0,
            total_model_count: 1,
            providers: [
              {
                provider: "local-orchestration",
                label: "vLLM",
                state: "available",
                ok: true,
                base_url: "https://runtime.internal.example/v1",
                default_model: "qwen3-coder-next",
                model_count: 1,
                message: "Detected 1 local orchestration model.",
                action: "Choose a detected vLLM model for local workflows."
              }
            ]
          }
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        durationMs: 5,
        url: `http://localhost${path}`,
        data: {}
      });
    });

    render(
      <ModelConnectionWizardPanel
        token="operator-token"
        apiKey=""
        onOpenSetup={vi.fn()}
        onOpenWorkflowCatalog={vi.fn()}
        onResult={vi.fn()}
      />
    );

    const providerPaths = await screen.findByRole("group", { name: "Provider setup paths" });
    expect(
      within(providerPaths).getByRole("button", { name: /^Local Startup runtime/ })
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("Base URL")).toHaveValue("https://runtime.internal.example/v1");
    expect(screen.getByLabelText("Default model")).toHaveValue("llamacpp/qwen3-coder-next");
    expect(screen.getByLabelText("Runtime engine")).toHaveValue("vLLM");
  });

  it("keeps the startup runtime path selected when the configured engine is Ollama", async () => {
    apiRequestMock.mockReset();
    apiRequestMock.mockImplementation(({ path }) => {
      if (path === "/v1/operator/config") {
        return Promise.resolve({
          ok: true,
          status: 200,
          durationMs: 5,
          url: "http://localhost/v1/operator/config",
          data: {
            groups: {
              llm: {
                default_model: "ollama/qwen3-coder",
                openrouter_base_url: "https://openrouter.ai/api/v1"
              },
              ollama: {
                ollama_base_url: "http://host.docker.internal:11434",
                ollama_default_model: "qwen3-coder"
              },
              lm_studio: {},
              local_orchestration: {
                local_orchestration_base_url: "http://host.docker.internal:8033/v1",
                local_orchestration_model: "qwen3-coder",
                local_orchestration_engine: "ollama"
              }
            }
          }
        });
      }
      if (path === "/v1/openrouter/models") {
        return Promise.resolve({
          ok: true,
          status: 200,
          durationMs: 5,
          url: "http://localhost/v1/openrouter/models",
          data: { data: [] }
        });
      }
      if (path === "/v1/model-health") {
        return Promise.resolve({
          ok: true,
          status: 200,
          durationMs: 5,
          url: "http://localhost/v1/model-health",
          data: {
            overall_state: "ready",
            summary: "2 local runtimes ready with 3 detected models.",
            ready_provider_count: 2,
            attention_provider_count: 0,
            total_model_count: 3,
            providers: [
              {
                provider: "ollama",
                label: "Ollama",
                state: "available",
                ok: true,
                base_url: "http://host.docker.internal:11434",
                model_count: 2,
                message: "Detected 2 local Ollama models.",
                action: "Choose a detected Ollama model for local workflows."
              },
              {
                provider: "local-orchestration",
                label: "Ollama",
                state: "available",
                ok: true,
                base_url: "http://host.docker.internal:11434",
                default_model: "qwen3-coder",
                model_count: 1,
                message: "Detected 1 startup Ollama model.",
                action: "Choose a detected Ollama model for local workflows."
              }
            ]
          }
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        durationMs: 5,
        url: `http://localhost${path}`,
        data: {}
      });
    });

    render(
      <ModelConnectionWizardPanel
        token="operator-token"
        apiKey=""
        onOpenSetup={vi.fn()}
        onOpenWorkflowCatalog={vi.fn()}
        onResult={vi.fn()}
      />
    );

    const providerPaths = await screen.findByRole("group", { name: "Provider setup paths" });
    expect(
      within(providerPaths).getByRole("button", { name: /^Local Startup runtime/ })
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("Base URL")).toHaveValue("http://host.docker.internal:11434");
    expect(screen.getByLabelText("Default model")).toHaveValue("ollama/qwen3-coder");
    expect(screen.getByLabelText("Runtime engine")).toHaveValue("ollama");
  });

  it("uses Ollama status for the local connection test", async () => {
    const user = userEvent.setup();
    render(
      <ModelConnectionWizardPanel
        token="operator-token"
        apiKey=""
        onOpenSetup={vi.fn()}
        onOpenWorkflowCatalog={vi.fn()}
        onResult={vi.fn()}
      />
    );

    const providerPaths = within(screen.getByRole("group", { name: "Provider setup paths" }));
    await user.click(providerPaths.getByRole("button", { name: /^Local Ollama/ }));
    const ollamaStatusPanel = getLocalRuntimePanel("Local Ollama status");
    expect(within(ollamaStatusPanel).getByText("Detected 2 local Ollama models.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Test connection" }));

    expect(await screen.findByText(/Ollama is ready at http:\/\/localhost:11434/)).toBeInTheDocument();
    await waitFor(() =>
      expect(apiRequestMock).not.toHaveBeenCalledWith(
        expect.objectContaining({ path: "/v1/openrouter/probe" })
      )
    );
  });

  it("shows detected LM Studio models and preserves the /v1 base URL", async () => {
    const user = userEvent.setup();
    render(
      <ModelConnectionWizardPanel
        token="operator-token"
        apiKey=""
        onOpenSetup={vi.fn()}
        onOpenWorkflowCatalog={vi.fn()}
        onResult={vi.fn()}
      />
    );

    const providerPaths = within(screen.getByRole("group", { name: "Provider setup paths" }));
    await user.click(providerPaths.getByRole("button", { name: /^Local LM Studio/ }));

    expect(screen.getByLabelText("Base URL")).toHaveValue("http://localhost:1234/v1");
    const lmStudioStatusPanel = getLocalRuntimePanel("Local LM Studio status");
    expect(within(lmStudioStatusPanel).getByText("Detected 2 LM Studio models.")).toBeInTheDocument();
    const detectedModels = within(screen.getByRole("group", { name: "Detected LM Studio models" }));
    await user.click(detectedModels.getByRole("button", { name: /mistral-nemo-instruct/ }));

    expect(screen.getByLabelText("Default model")).toHaveValue("lmstudio/mistral-nemo-instruct");
    expect(apiRequestMock).toHaveBeenCalledWith(
      expect.objectContaining({
        method: "GET",
        path: "/v1/lm-studio/status",
        query: undefined
      })
    );
  });

  it("uses LM Studio status for the local connection test", async () => {
    const user = userEvent.setup();
    render(
      <ModelConnectionWizardPanel
        token="operator-token"
        apiKey=""
        onOpenSetup={vi.fn()}
        onOpenWorkflowCatalog={vi.fn()}
        onResult={vi.fn()}
      />
    );

    const providerPaths = within(screen.getByRole("group", { name: "Provider setup paths" }));
    await user.click(providerPaths.getByRole("button", { name: /^Local LM Studio/ }));
    const lmStudioStatusPanel = getLocalRuntimePanel("Local LM Studio status");
    expect(within(lmStudioStatusPanel).getByText("Detected 2 LM Studio models.")).toBeInTheDocument();
    const detectedModels = within(screen.getByRole("group", { name: "Detected LM Studio models" }));
    await user.click(detectedModels.getByRole("button", { name: /qwen2.5-coder-7b-instruct/ }));
    await user.click(screen.getByRole("button", { name: "Test connection" }));

    expect(await screen.findByText(/LM Studio is ready at http:\/\/localhost:1234\/v1/)).toBeInTheDocument();
    await waitFor(() =>
      expect(apiRequestMock).not.toHaveBeenCalledWith(
        expect.objectContaining({ path: "/v1/openrouter/probe" })
      )
    );
  });

  it("passes an LM Studio override only when the operator edits the configured URL", async () => {
    const user = userEvent.setup();
    render(
      <ModelConnectionWizardPanel
        token="operator-token"
        apiKey=""
        onOpenSetup={vi.fn()}
        onOpenWorkflowCatalog={vi.fn()}
        onResult={vi.fn()}
      />
    );

    const providerPaths = within(screen.getByRole("group", { name: "Provider setup paths" }));
    await user.click(providerPaths.getByRole("button", { name: /^Local LM Studio/ }));
    const lmStudioStatusPanel = getLocalRuntimePanel("Local LM Studio status");
    expect(within(lmStudioStatusPanel).getByText("Detected 2 LM Studio models.")).toBeInTheDocument();
    const baseUrlInput = screen.getByLabelText("Base URL");
    await user.clear(baseUrlInput);
    await user.type(baseUrlInput, "http://127.0.0.1:1234");
    await user.click(screen.getByRole("button", { name: "Test connection" }));

    await waitFor(() =>
      expect(apiRequestMock).toHaveBeenCalledWith(
        expect.objectContaining({
          method: "GET",
          path: "/v1/lm-studio/status",
          query: { base_url: "http://127.0.0.1:1234/v1" }
        })
      )
    );
  });

  it("shows capability labels on recommended models", () => {
    render(
      <ModelConnectionWizardPanel
        token=""
        apiKey=""
        onOpenSetup={vi.fn()}
        onOpenWorkflowCatalog={vi.fn()}
        onResult={vi.fn()}
      />
    );

    expect(screen.getAllByText("Best for coding").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Fast start").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Long context").length).toBeGreaterThan(0);
  });
});
