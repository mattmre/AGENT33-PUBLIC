import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { HelpAssistantDrawer } from "./HelpAssistantDrawer";

vi.mock("./ragApi", () => ({
  ragQuery: vi.fn().mockResolvedValue({
    augmented_prompt: "RAG answer about setup",
    sources: [{ text: "source text", score: 0.8, metadata: {}, retrieval_method: "vector" }],
    citations: []
  }),
  ollamaQuery: vi.fn().mockResolvedValue({
    text: "Ollama sidecar answer",
    sources: []
  })
}));

import { ollamaQuery, ragQuery } from "./ragApi";
const mockRagQuery = vi.mocked(ragQuery);
const mockOllamaQuery = vi.mocked(ollamaQuery);

describe("HelpAssistantDrawer", () => {
  beforeEach(() => {
    mockRagQuery.mockReset();
    mockOllamaQuery.mockReset();
  });
  it("opens the offline assistant and answers OpenRouter setup questions with citations", async () => {
    const user = userEvent.setup();

    render(<HelpAssistantDrawer onNavigate={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "Ask AGENT33" }));
    await user.type(screen.getByPlaceholderText("How do I connect OpenRouter?"), "connect openrouter");

    expect(screen.getByRole("heading", { name: "Connect OpenRouter" })).toBeInTheDocument();
    expect(screen.getByText(/OPENROUTER_API_KEY/)).toBeInTheDocument();
    expect(screen.getByText(/does not call an external model/)).toBeInTheDocument();
    expect(screen.getByText("Sources used for this answer")).toBeInTheDocument();
  });

  it("routes action buttons through the app navigation callback", async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();

    render(<HelpAssistantDrawer onNavigate={onNavigate} />);

    await user.click(screen.getByRole("button", { name: "Ask AGENT33" }));
    await user.click(screen.getByRole("button", { name: "Connect OpenRouter" }));
    await user.click(screen.getByRole("button", { name: "Open Models" }));

    expect(onNavigate).toHaveBeenCalledWith("models");
  });

  it("opens Connect Center directly from the assistant", async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();

    render(<HelpAssistantDrawer onNavigate={onNavigate} />);

    await user.click(screen.getByRole("button", { name: "Ask AGENT33" }));
    await user.click(screen.getByRole("button", { name: "Open Connect Center" }));

    expect(onNavigate).toHaveBeenCalledWith("connect");
  });

  it("lets users choose helper runtime modes without starting a model", async () => {
    const user = userEvent.setup();

    render(<HelpAssistantDrawer onNavigate={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "Ask AGENT33" }));

    expect(screen.getByRole("heading", { name: "Choose how the helper thinks" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Static cited search/ })).toHaveAttribute(
      "aria-pressed",
      "true"
    );

    await user.click(screen.getByRole("button", { name: /Ollama sidecar helper/ }));

    expect(screen.getByRole("button", { name: /Ollama sidecar helper/ })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    expect(screen.getByText("Start Ollama locally")).toBeInTheDocument();
  });

  it("calls ragQuery when browser-semantic mode is selected and query is entered", async () => {
    const user = userEvent.setup();
    mockRagQuery.mockResolvedValue({
      augmented_prompt: "RAG answer about setup",
      sources: [{ text: "source text", score: 0.8, metadata: {}, retrieval_method: "vector" }],
      citations: []
    });

    render(<HelpAssistantDrawer onNavigate={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Ask AGENT33" }));
    await user.click(screen.getByRole("button", { name: /Browser semantic search/ }));
    await user.type(screen.getByPlaceholderText("How do I connect OpenRouter?"), "connect");

    await waitFor(() => {
      expect(mockRagQuery).toHaveBeenCalled();
    });

    await waitFor(() => {
      expect(screen.getByText("RAG answer about setup")).toBeInTheDocument();
    });
  });

  it("calls ollamaQuery when ollama-sidecar mode is selected and query is entered", async () => {
    const user = userEvent.setup();
    mockOllamaQuery.mockResolvedValue({ text: "Ollama sidecar answer", sources: [] });

    render(<HelpAssistantDrawer onNavigate={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Ask AGENT33" }));
    await user.click(screen.getByRole("button", { name: /Ollama sidecar helper/ }));
    await user.type(screen.getByPlaceholderText("How do I connect OpenRouter?"), "ollama test");

    await waitFor(() => {
      expect(mockOllamaQuery).toHaveBeenCalled();
    });

    await waitFor(() => {
      expect(screen.getByText("Ollama sidecar answer")).toBeInTheDocument();
    });
  });

  it("shows a fallback error message when RAG backend is unreachable", async () => {
    const user = userEvent.setup();
    mockRagQuery.mockRejectedValue(new Error("network error"));

    render(<HelpAssistantDrawer onNavigate={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Ask AGENT33" }));
    await user.click(screen.getByRole("button", { name: /Browser semantic search/ }));
    await user.type(screen.getByPlaceholderText("How do I connect OpenRouter?"), "connect");

    await waitFor(() => {
      expect(
        screen.getByText(/Could not reach the helper backend/)
      ).toBeInTheDocument();
    });
  });
});
