import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  ProviderModelHealthSummary,
  type LocalModelHealth
} from "./ProviderModelHealthSummary";

const readyHealth: LocalModelHealth = {
  overallState: "ready",
  summary: "1 local runtime ready with 2 detected models.",
  readyProviderCount: 1,
  attentionProviderCount: 1,
  totalModelCount: 2,
  providers: [
    {
      provider: "ollama",
      label: "Ollama",
      state: "available",
      ok: true,
      baseUrl: "http://localhost:11434",
      defaultModel: "ollama/qwen2.5-coder:7b",
      modelCount: 2,
      message: "Detected 2 local Ollama models.",
      action: "Choose a detected Ollama model for local workflows."
    },
    {
      provider: "lm-studio",
      label: "LM Studio",
      state: "empty",
      ok: false,
      baseUrl: "http://localhost:1234/v1",
      defaultModel: "",
      modelCount: 0,
      message: "LM Studio is reachable but no models are loaded.",
      action: "Install or load a model in LM Studio, then refresh health."
    }
  ]
};

describe("ProviderModelHealthSummary", () => {
  it("summarizes ready and attention local runtimes", () => {
    render(
      <ProviderModelHealthSummary
        health={readyHealth}
        isLoading={false}
        hasCredentials={true}
        selectedPresetId="ollama"
        selectedProviderName="Ollama"
        onRefresh={vi.fn()}
      />
    );

    expect(screen.getByText("1 local runtime ready with 2 detected models.")).toBeInTheDocument();
    expect(screen.getByText("Ollama")).toBeInTheDocument();
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.getByText("LM Studio")).toBeInTheDocument();
    expect(screen.getByText("Needs a model")).toBeInTheDocument();
    expect(screen.getByText(/You are editing Ollama/)).toBeInTheDocument();
  });

  it("explains credential and cloud-provider states", () => {
    render(
      <ProviderModelHealthSummary
        health={null}
        isLoading={false}
        hasCredentials={false}
        selectedPresetId="openrouter"
        selectedProviderName="OpenRouter"
        onRefresh={vi.fn()}
      />
    );

    expect(
      screen.getByText("Connect engine access first so AGENT-33 can check local model health.")
    ).toBeInTheDocument();
    expect(screen.getByText(/Cloud providers still use the Test connection button/)).toBeInTheDocument();
  });

  it("calls refresh when requested", async () => {
    const user = userEvent.setup();
    const onRefresh = vi.fn();
    render(
      <ProviderModelHealthSummary
        health={readyHealth}
        isLoading={false}
        hasCredentials={true}
        selectedPresetId="lm-studio"
        selectedProviderName="LM Studio"
        onRefresh={onRefresh}
      />
    );

    await user.click(screen.getByRole("button", { name: "Refresh local health" }));

    expect(onRefresh).toHaveBeenCalledTimes(1);
  });
});
