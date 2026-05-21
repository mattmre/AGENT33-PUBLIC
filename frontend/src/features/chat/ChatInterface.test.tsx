import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

const { apiRequestMock } = vi.hoisted(() => ({
  apiRequestMock: vi.fn()
}))

vi.mock("../../lib/api", () => ({
  apiRequest: apiRequestMock,
  getRuntimeConfig: () => ({ API_BASE_URL: "http://localhost:8000" })
}))

import { ChatInterface } from "./ChatInterface"

const catalogResponse = {
  models: [
    {
      id: "qwen/qwen3-coder-flash",
      name: "Qwen3 Coder Flash",
      description: "Fast verified coding model",
      vendor: "qwen",
      context_length: 256000,
      pricing: { prompt: "0.0000005", completion: "0.0000015" },
      supported_parameters: ["tools", "reasoning"],
      top_provider: { max_completion_tokens: 65536 }
    },
    {
      id: "qwen/qwen3-coder-30b-a3b-instruct",
      name: "Qwen3 Coder 30B A3B Instruct",
      description: "Larger verified instruct model",
      vendor: "qwen",
      context_length: 256000,
      pricing: { prompt: "0.0000015", completion: "0.0000045" },
      supported_parameters: ["tools", "reasoning"],
      top_provider: { max_completion_tokens: 32768 }
    },
    {
      id: "qwen/qwen3-32b",
      name: "Qwen3 32B",
      description: "Known-working general purpose Qwen option",
      vendor: "qwen",
      context_length: 256000,
      pricing: { prompt: "0.0000012", completion: "0.0000038" },
      top_provider: { max_completion_tokens: 32768 }
    },
    {
      id: "openai/gpt-5.2",
      name: "GPT-5.2",
      description: "Fast general purpose model",
      vendor: "openai",
      context_length: 128000,
      pricing: { prompt: "0.000002", completion: "0.000008" },
      supported_parameters: ["tools", "reasoning"],
      top_provider: { max_completion_tokens: 4096 }
    },
    {
      id: "anthropic/claude-3.7-sonnet",
      name: "Claude 3.7 Sonnet",
      description: "Reasoning-focused model",
      vendor: "anthropic",
      context_length: 200000,
      pricing: { prompt: "0.000003", completion: "0.000015" },
      capabilities: ["reasoning"],
      top_provider: { max_completion_tokens: 8192, is_moderated: true }
    }
  ]
}

// SpeechSynthesis and SpeechRecognition are browser APIs not available in jsdom.
// Stub them so the component can mount without crashing.
function stubSpeechApis() {
  const speechSynthesisMock = {
    getVoices: vi.fn().mockReturnValue([]),
    speak: vi.fn(),
    cancel: vi.fn(),
    onvoiceschanged: null as (() => void) | null,
    speaking: false
  }
  Object.defineProperty(window, "speechSynthesis", {
    value: speechSynthesisMock,
    writable: true,
    configurable: true
  })
  return speechSynthesisMock
}

// jsdom does not implement scrollIntoView; stub it so the component can render.
beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn()
})

describe("ChatInterface", () => {
  beforeEach(() => {
    stubSpeechApis()
  })

  afterEach(() => {
    vi.clearAllMocks()
    window.localStorage.clear()
  })

  it("renders the initial assistant greeting", () => {
    render(<ChatInterface token="jwt" apiKey="" />)

    expect(
      screen.getByText("Hello! I am AGENT-33. How can I assist you today?")
    ).toBeInTheDocument()
  })

  it("renders the message input area", () => {
    render(<ChatInterface token="jwt" apiKey="" />)

    expect(
      screen.getByPlaceholderText("Message AGENT-33 (or click the mic to speak)...")
    ).toBeInTheDocument()
  })

  it("sends a user message and displays the assistant reply", async () => {
    const user = userEvent.setup()

    apiRequestMock.mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        choices: [
          {
            message: {
              content: "I can help with that workflow."
            }
          }
        ]
      }
    })

    render(<ChatInterface token="jwt" apiKey="key" />)

    const textarea = screen.getByPlaceholderText(
      "Message AGENT-33 (or click the mic to speak)..."
    )
    await user.type(textarea, "Run my workflow")
    await user.click(screen.getByTitle("Send (Enter)"))

    expect(screen.getByText("Run my workflow")).toBeInTheDocument()

    await waitFor(() => {
      expect(
        screen.getByText("I can help with that workflow.")
      ).toBeInTheDocument()
    })

    expect(apiRequestMock).toHaveBeenCalledWith(
      expect.objectContaining({
        method: "POST",
        path: "/v1/chat/completions"
      })
    )

    const body = JSON.parse(apiRequestMock.mock.calls[0][0].body as string)
    expect(body.model).toBeUndefined()
    expect(body.temperature).toBe(0.2)
    const lastMessage = body.messages[body.messages.length - 1]
    expect(lastMessage.role).toBe("user")
    expect(lastMessage.content).toBe("Run my workflow")
  })

  it("uses a configured model override when sending chat requests", async () => {
    const user = userEvent.setup()

    apiRequestMock.mockImplementation(async (args: { path: string }) => {
      if (args.path === "/v1/openrouter/models") {
        return {
          ok: false,
          status: 503,
          data: { message: "Catalog unavailable" }
        }
      }

      return {
        ok: true,
        status: 200,
        data: { choices: [{ message: { content: "Using the chosen model." } }] }
      }
    })

    render(<ChatInterface token="jwt" apiKey="" />)

    await user.click(screen.getByTitle("Chat Settings"))
    await user.click(screen.getByText("Model & Provider"))
    await screen.findByText("Catalog unavailable")
    await user.type(screen.getByLabelText("Model override"), "openrouter/auto")

    const textarea = screen.getByPlaceholderText(
      "Message AGENT-33 (or click the mic to speak)..."
    )
    await user.type(textarea, "Use OpenRouter")
    await user.click(screen.getByTitle("Send (Enter)"))

    const chatCall = apiRequestMock.mock.calls.find(
      ([args]) => args.path === "/v1/chat/completions"
    )
    if (!chatCall) {
      throw new Error("Expected a chat completion request")
    }

    const body = JSON.parse(chatCall[0].body as string)
    expect(body.model).toBe("openrouter/auto")
  })

  it("normalizes likely OpenRouter catalog ids before sending chat requests", async () => {
    const user = userEvent.setup()

    apiRequestMock.mockImplementation(async (args: { path: string }) => {
      if (args.path === "/v1/openrouter/models") {
        return {
          ok: false,
          status: 503,
          data: { message: "Catalog unavailable" }
        }
      }

      return {
        ok: true,
        status: 200,
        data: { choices: [{ message: { content: "Using the normalized model." } }] }
      }
    })

    render(<ChatInterface token="jwt" apiKey="" />)

    await user.click(screen.getByTitle("Chat Settings"))
    await user.click(screen.getByText("Model & Provider"))
    await screen.findByText("Catalog unavailable")
    await user.type(screen.getByLabelText("Model override"), "qwen/qwen3-32b")

    const textarea = screen.getByPlaceholderText(
      "Message AGENT-33 (or click the mic to speak)..."
    )
    await user.type(textarea, "Use OpenRouter catalog id")
    await user.click(screen.getByTitle("Send (Enter)"))

    const chatCall = apiRequestMock.mock.calls.find(
      ([args]) => args.path === "/v1/chat/completions"
    )
    if (!chatCall) {
      throw new Error("Expected a chat completion request")
    }

    const body = JSON.parse(chatCall[0].body as string)
    expect(body.model).toBe("openrouter/qwen/qwen3-32b")
    expect(screen.getByLabelText("Model override")).toHaveValue("openrouter/qwen/qwen3-32b")
  })

  it("loads the live model catalog and applies a selected model override", async () => {
    const user = userEvent.setup()

    apiRequestMock.mockImplementation(async (args: { path: string }) => {
      if (args.path === "/v1/openrouter/models") {
        return {
          ok: true,
      status: 200,
      data: catalogResponse
    }
      }

      return {
        ok: true,
        status: 200,
        data: { choices: [{ message: { content: "Model picker applied." } }] }
      }
    })

    render(<ChatInterface token="jwt" apiKey="" />)

    await user.click(screen.getByTitle("Chat Settings"))
    await user.click(screen.getByText("Model & Provider"))
    await screen.findByText("Loaded 5 models from the live catalog.")
    await user.type(screen.getByLabelText("Search model catalog"), "claude")
    await user.click(screen.getByRole("button", { name: "Use Claude 3.7 Sonnet" }))

    expect(screen.getByLabelText("Model override")).toHaveValue(
      "openrouter/anthropic/claude-3.7-sonnet"
    )

    const textarea = screen.getByPlaceholderText(
      "Message AGENT-33 (or click the mic to speak)..."
    )
    await user.type(textarea, "Use picker")
    await user.click(screen.getByTitle("Send (Enter)"))

    const chatCall = apiRequestMock.mock.calls.find(
      ([args]) => args.path === "/v1/chat/completions"
    )
    if (!chatCall) {
      throw new Error("Expected a chat completion request")
    }

    const body = JSON.parse(chatCall[0].body as string)
    expect(body.model).toBe("openrouter/anthropic/claude-3.7-sonnet")
  })

  it("shows known-working recovery picks and warns for catalog-only overrides", async () => {
    const user = userEvent.setup()

    apiRequestMock.mockImplementation(async (args: { path: string }) => {
      if (args.path === "/v1/openrouter/models") {
        return {
          ok: true,
          status: 200,
          data: catalogResponse
        }
      }

      return {
        ok: true,
        status: 200,
        data: { choices: [{ message: { content: "ok" } }] }
      }
    })

    render(<ChatInterface token="jwt" apiKey="" />)

    await user.click(screen.getByTitle("Chat Settings"))
    await user.click(screen.getByText("Model & Provider"))
    await screen.findByText("Known working models")
    expect(
      screen.getByText(/Catalog results can still fail for your OpenRouter account or provider route/)
    ).toBeInTheDocument()

    await user.click(
      screen.getByRole("button", {
        name: "Use openrouter/qwen/qwen3-coder-flash as chat model override"
      })
    )
    expect(screen.getByLabelText("Model override")).toHaveValue(
      "openrouter/qwen/qwen3-coder-flash"
    )
    expect(screen.getAllByText("Stable default").length).toBeGreaterThan(0)
    expect(screen.queryByText(/catalog\/manual only/)).not.toBeInTheDocument()

    await user.type(screen.getByLabelText("Search model catalog"), "claude")
    await user.click(screen.getByRole("button", { name: "Use Claude 3.7 Sonnet" }))

    expect(screen.getByLabelText("Model override")).toHaveValue(
      "openrouter/anthropic/claude-3.7-sonnet"
    )
    expect(screen.getByText("Catalog/manual model")).toBeInTheDocument()
    expect(
      screen.getByText(/Catalog presence does not guarantee your account\/provider can route it/)
    ).toBeInTheDocument()
  })

  it("can clear a browser-local model override and fall back to the server default", async () => {
    const user = userEvent.setup()
    window.localStorage.setItem("agent33.chatModel", "openrouter/openai/gpt-5.2")

    apiRequestMock.mockImplementation(async (args: { path: string }) => {
      if (args.path === "/v1/openrouter/models") {
        return {
          ok: true,
          status: 200,
          data: catalogResponse
        }
      }

      return {
        ok: true,
        status: 200,
        data: { choices: [{ message: { content: "Using default model." } }] }
      }
    })

    render(<ChatInterface token="jwt" apiKey="" />)

    await user.click(screen.getByTitle("Chat Settings"))
    await user.click(screen.getByText("Model & Provider"))
    expect(screen.getByLabelText("Model override")).toHaveValue("openrouter/openai/gpt-5.2")

    await user.click(screen.getByRole("button", { name: "Use server default" }))

    expect(screen.getByLabelText("Model override")).toHaveValue("")
    await waitFor(() => {
      expect(window.localStorage.getItem("agent33.chatModel")).toBe("")
    })

    const textarea = screen.getByPlaceholderText(
      "Message AGENT-33 (or click the mic to speak)..."
    )
    await user.type(textarea, "Use default")
    await user.click(screen.getByTitle("Send (Enter)"))

    const chatCall = apiRequestMock.mock.calls.find(
      ([args]) => args.path === "/v1/chat/completions"
    )
    if (!chatCall) {
      throw new Error("Expected a chat completion request")
    }

    const body = JSON.parse(chatCall[0].body as string)
    expect(body.model).toBeUndefined()
  })

  it("clears the input after sending", async () => {
    const user = userEvent.setup()

    apiRequestMock.mockResolvedValue({
      ok: true,
      status: 200,
      data: { choices: [{ message: { content: "done" } }] }
    })

    render(<ChatInterface token="jwt" apiKey="" />)

    const textarea = screen.getByPlaceholderText(
      "Message AGENT-33 (or click the mic to speak)..."
    )
    await user.type(textarea, "hello")
    await user.click(screen.getByTitle("Send (Enter)"))

    expect(textarea).toHaveValue("")
  })

  it("shows loading indicator while waiting for response", async () => {
    const user = userEvent.setup()
    let resolveApi: (value: unknown) => void = () => {}

    apiRequestMock.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveApi = resolve
        })
    )

    render(<ChatInterface token="jwt" apiKey="" />)

    const textarea = screen.getByPlaceholderText(
      "Message AGENT-33 (or click the mic to speak)..."
    )
    await user.type(textarea, "test")
    await user.click(screen.getByTitle("Send (Enter)"))

    expect(textarea).toBeDisabled()
    expect(document.querySelector(".typing-indicator")).not.toBeNull()

    resolveApi({
      ok: true,
      status: 200,
      data: { choices: [{ message: { content: "reply" } }] }
    })

    await waitFor(() => {
      expect(textarea).toBeEnabled()
    })
  })

  it("displays an error message when API returns 401", async () => {
    const user = userEvent.setup()

    apiRequestMock.mockResolvedValue({
      ok: false,
      status: 401,
      data: null
    })

    render(<ChatInterface token="jwt" apiKey="" />)

    const textarea = screen.getByPlaceholderText(
      "Message AGENT-33 (or click the mic to speak)..."
    )
    await user.type(textarea, "test")
    await user.click(screen.getByTitle("Send (Enter)"))

    await waitFor(() => {
      expect(
        screen.getByText(/Unauthorized \(401\)/)
      ).toBeInTheDocument()
    })
  })

  it("displays an error message when API returns a non-401 error", async () => {
    const user = userEvent.setup()

    apiRequestMock.mockResolvedValue({
      ok: false,
      status: 500,
      data: null
    })

    render(<ChatInterface token="jwt" apiKey="" />)

    const textarea = screen.getByPlaceholderText(
      "Message AGENT-33 (or click the mic to speak)..."
    )
    await user.type(textarea, "test")
    await user.click(screen.getByTitle("Send (Enter)"))

    await waitFor(() => {
      expect(screen.getByText(/API Error: 500/)).toBeInTheDocument()
    })
  })

  it("displays error when apiRequest throws a network error", async () => {
    const user = userEvent.setup()

    apiRequestMock.mockRejectedValue(new Error("Connection refused"))

    render(<ChatInterface token="jwt" apiKey="" />)

    const textarea = screen.getByPlaceholderText(
      "Message AGENT-33 (or click the mic to speak)..."
    )
    await user.type(textarea, "test")
    await user.click(screen.getByTitle("Send (Enter)"))

    await waitFor(() => {
      expect(screen.getByText(/Connection refused/)).toBeInTheDocument()
    })
  })

  it("sends message on Enter key (without Shift)", async () => {
    const user = userEvent.setup()

    apiRequestMock.mockResolvedValue({
      ok: true,
      status: 200,
      data: { choices: [{ message: { content: "reply via enter" } }] }
    })

    render(<ChatInterface token="jwt" apiKey="" />)

    const textarea = screen.getByPlaceholderText(
      "Message AGENT-33 (or click the mic to speak)..."
    )
    await user.type(textarea, "enter test{enter}")

    await waitFor(() => {
      expect(screen.getByText("reply via enter")).toBeInTheDocument()
    })
  })

  it("does not send on empty input", async () => {
    const user = userEvent.setup()

    render(<ChatInterface token="jwt" apiKey="" />)

    await user.click(screen.getByTitle("Send (Enter)"))

    expect(apiRequestMock).not.toHaveBeenCalled()
  })

  it("does not render system messages in the chat", () => {
    render(<ChatInterface token="jwt" apiKey="" />)

    expect(
      screen.queryByText("You are a helpful AI assistant.")
    ).not.toBeInTheDocument()
  })

  it("shows settings popover when gear button is clicked", async () => {
    const user = userEvent.setup()

    render(<ChatInterface token="jwt" apiKey="" />)

    await user.click(screen.getByTitle("Chat Settings"))

    expect(screen.getByText("Chat Settings")).toBeInTheDocument()
    expect(screen.getByText("Translation Options")).toBeInTheDocument()
    expect(screen.getByText("Audio Response")).toBeInTheDocument()
  })

  it("closes settings popover with close button", async () => {
    const user = userEvent.setup()

    render(<ChatInterface token="jwt" apiKey="" />)

    await user.click(screen.getByTitle("Chat Settings"))
    expect(screen.getByText("Chat Settings")).toBeInTheDocument()

    const closeBtn = document.querySelector(".settings-close-btn")
    expect(closeBtn).not.toBeNull()
    await user.click(closeBtn!)

    expect(screen.queryByText("Translation Options")).not.toBeInTheDocument()
  })

  it("passes auth credentials through to the API request", async () => {
    const user = userEvent.setup()

    apiRequestMock.mockResolvedValue({
      ok: true,
      status: 200,
      data: { choices: [{ message: { content: "ok" } }] }
    })

    render(<ChatInterface token="my-jwt-token" apiKey="a33_key" />)

    const textarea = screen.getByPlaceholderText(
      "Message AGENT-33 (or click the mic to speak)..."
    )
    await user.type(textarea, "hello{enter}")

    await waitFor(() => {
      expect(apiRequestMock).toHaveBeenCalledTimes(1)
    })

    expect(apiRequestMock).toHaveBeenCalledWith(
      expect.objectContaining({
        token: "my-jwt-token",
        apiKey: "a33_key"
      })
    )
  })
})
