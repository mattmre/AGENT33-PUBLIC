import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

const { apiRequestMock } = vi.hoisted(() => ({
  apiRequestMock: vi.fn()
}))

vi.mock("../../lib/api", () => ({
  apiRequest: apiRequestMock
}))

import { MessagingSetup } from "./MessagingSetup"

function buildApiResult(data: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    data,
    durationMs: 12,
    url: "http://localhost:8000/mock"
  }
}

const configResponse = {
  groups: {
    llm: {
      openrouter_api_key: "***",
      openrouter_base_url: "https://openrouter.ai/api/v1",
      openrouter_site_url: "https://agent33.example",
      openrouter_app_name: "Agent Console",
      openrouter_app_category: "ops-console",
      default_model: "openrouter/qwen/qwen3-coder-flash"
    },
    ollama: {
      default_model: "openrouter/qwen/qwen3-coder-flash"
    }
  }
}

const catalogResponse = {
  data: [
    {
      id: "qwen/qwen3-coder-flash",
      name: "Qwen3 Coder Flash",
      description: "Fast verified coding model",
      context_length: 256000,
      pricing: { prompt: "0.0000005", completion: "0.0000015" },
      supported_parameters: ["tools", "reasoning"],
      top_provider: { max_completion_tokens: 65536 }
    },
    {
      id: "qwen/qwen3-coder-30b-a3b-instruct",
      name: "Qwen3 Coder 30B A3B Instruct",
      description: "Larger verified instruct model",
      context_length: 256000,
      pricing: { prompt: "0.0000015", completion: "0.0000045" },
      supported_parameters: ["tools", "reasoning"],
      top_provider: { max_completion_tokens: 32768 }
    },
    {
      id: "qwen/qwen3-32b",
      name: "Qwen3 32B",
      description: "Known-working general purpose Qwen option",
      context_length: 256000,
      pricing: { prompt: "0.0000012", completion: "0.0000038" },
      top_provider: { max_completion_tokens: 32768 }
    },
    {
      id: "openai/gpt-5.2",
      name: "GPT-5.2",
      description: "Fast general purpose model",
      context_length: 128000,
      pricing: { prompt: "0.000002", completion: "0.000008" },
      supported_parameters: ["tools", "reasoning"],
      architecture: { modality: "text->text", instruct_type: "chat" },
      top_provider: { max_completion_tokens: 4096 }
    },
    {
      id: "anthropic/claude-3.7-sonnet",
      name: "Claude 3.7 Sonnet",
      description: "Reasoning-focused model",
      context_length: 200000,
      pricing: { prompt: "0.000003", completion: "0.000015" },
      capabilities: ["reasoning"],
      top_provider: { max_completion_tokens: 8192, is_moderated: true }
    }
  ]
}

function buildCatalogModel(index: number) {
  return {
    id: `provider/model-${index}`,
    name: `Model ${index}`,
    description: `Catalog model ${index}`,
    context_length: 128000 + index,
    pricing: { prompt: "0.000001", completion: "0.000002" },
    supported_parameters: ["tools"],
    top_provider: { max_completion_tokens: 4096 }
  }
}

function mockApiRoutes(): void {
  apiRequestMock.mockReset()
  apiRequestMock.mockImplementation(async (args: { path: string }) => {
    if (args.path === "/v1/operator/config") {
      return buildApiResult(configResponse)
    }

    if (args.path === "/v1/openrouter/models") {
      return buildApiResult(catalogResponse)
    }

    if (args.path === "/v1/config/apply") {
      return buildApiResult({
        applied: ["default_model", "openrouter_api_key"],
        rejected: [],
        validation_errors: [],
        restart_required: true
      })
    }

    if (args.path === "/v1/openrouter/probe") {
      return buildApiResult({
        ok: true,
        message: "Connection ok",
        model: "openrouter/qwen/qwen3-coder-flash",
        latency_ms: 321
      })
    }

    if (args.path === "/v1/connectors/messaging/register") {
      return buildApiResult({
        adapter: "telegram",
        status: "ok",
        detail: "Health check status: ok"
      })
    }

    throw new Error(`Unhandled path: ${args.path}`)
  })
}

describe("MessagingSetup", () => {
  beforeEach(() => {
    mockApiRoutes()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("renders the messaging integrations heading and cards", async () => {
    render(<MessagingSetup />)

    expect(screen.getByText("Messaging Integrations")).toBeInTheDocument()
    expect(
      screen.getByText(
        "Connect your agent to external messaging platforms to chat from anywhere."
      )
    ).toBeInTheDocument()

    expect(screen.getByText("OpenRouter")).toBeInTheDocument()
    expect(screen.getByText("Telegram")).toBeInTheDocument()
    expect(screen.getByText("Discord")).toBeInTheDocument()
    expect(screen.getByText("Signal")).toBeInTheDocument()
    expect(screen.getByText("iMessage")).toBeInTheDocument()

    expect(await screen.findByText("Loaded 5 OpenRouter models.")).toBeInTheDocument()
  })

  it("loads redacted config and catalog data into the OpenRouter card", async () => {
    const user = userEvent.setup()

    render(<MessagingSetup />)

    expect(
      await screen.findByDisplayValue("openrouter/qwen/qwen3-coder-flash")
    ).toBeInTheDocument()
    expect(
      screen.getByText(/A server-side OpenRouter key is already configured/)
    ).toBeInTheDocument()
    expect(
      screen.getByText(/The public OpenRouter catalog can list models that are not enabled/)
    ).toBeInTheDocument()
    expect(screen.getByText("Known working models")).toBeInTheDocument()
    expect(screen.getAllByText("Stable default")[0]).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "Show advanced settings" }))

    expect(screen.getByDisplayValue("https://openrouter.ai/api/v1")).toBeInTheDocument()
    expect(screen.getByDisplayValue("https://agent33.example")).toBeInTheDocument()
    expect(screen.getByDisplayValue("Agent Console")).toBeInTheDocument()
    expect(screen.getByDisplayValue("ops-console")).toBeInTheDocument()

    const catalog = screen.getByRole("list", {
      name: "OpenRouter model catalog results"
    })

    expect(
      within(catalog).getByRole("heading", { name: "Qwen3 Coder Flash" })
    ).toBeInTheDocument()
    expect(within(catalog).getByRole("heading", { name: "GPT-5.2" })).toBeInTheDocument()
    expect(
      within(catalog).getByRole("heading", { name: "Claude 3.7 Sonnet" })
    ).toBeInTheDocument()
    expect(screen.getByText("Prompt $0.5000/M")).toBeInTheDocument()
    expect(screen.getByText("Completion $1.50/M")).toBeInTheDocument()
  })

  it("uses assertive alert semantics for errors while keeping polite status updates", async () => {
    apiRequestMock.mockReset()
    apiRequestMock.mockImplementation(async (args: { path: string }) => {
      if (args.path === "/v1/operator/config") {
        return buildApiResult({ message: "Config unavailable" }, false, 500)
      }

      if (args.path === "/v1/openrouter/models") {
        return buildApiResult(catalogResponse)
      }

      throw new Error(`Unhandled path: ${args.path}`)
    })

    render(<MessagingSetup />)

    const configAlert = await screen.findByRole("alert")
    expect(configAlert).toHaveTextContent("Config unavailable")
    expect(configAlert).not.toHaveAttribute("aria-live")
    expect(await screen.findByText("Loaded 5 OpenRouter models.")).toBeInTheDocument()
    expect(screen.getByText("Loaded 5 OpenRouter models.").closest('[role="status"]')).toHaveAttribute(
      "aria-live",
      "polite"
    )
  })

  it("limits default-model datalist options and narrows them as the input changes", async () => {
    const user = userEvent.setup()
    const blankConfigResponse = {
      groups: {
        llm: {
          ...configResponse.groups.llm,
          default_model: ""
        },
        ollama: {
          ...configResponse.groups.ollama,
          default_model: ""
        }
      }
    }
    const largeCatalogResponse = {
      data: Array.from({ length: 75 }, (_, index) => buildCatalogModel(index))
    }

    apiRequestMock.mockReset()
    apiRequestMock.mockImplementation(async (args: { path: string }) => {
      if (args.path === "/v1/operator/config") {
        return buildApiResult(blankConfigResponse)
      }

      if (args.path === "/v1/openrouter/models") {
        return buildApiResult(largeCatalogResponse)
      }

      throw new Error(`Unhandled path: ${args.path}`)
    })

    render(<MessagingSetup />)

    expect(await screen.findByText("Loaded 75 OpenRouter models.")).toBeInTheDocument()
    const getOptions = () => Array.from(document.querySelectorAll("#openrouter-model-options option"))

    expect(getOptions()).toHaveLength(50)

    await user.type(screen.getByLabelText("Default model"), "model-59")

    await waitFor(() => {
      expect(getOptions()).toHaveLength(1)
    })
    expect(getOptions()[0]).toHaveAttribute("value", "openrouter/provider/model-59")
  })

  it("saves OpenRouter settings through config apply without using browser storage", async () => {
    const user = userEvent.setup()

    render(<MessagingSetup />)

    await screen.findByDisplayValue("openrouter/qwen/qwen3-coder-flash")
    await user.clear(screen.getByLabelText("Default model"))
    await user.type(screen.getByLabelText("Default model"), "qwen/qwen3-32b")
    await user.type(screen.getByLabelText("API key"), "sk-or-test-123")
    await user.click(
      screen.getByLabelText("Persist these settings to the server .env file for restarts")
    )
    await user.click(screen.getByRole("button", { name: "Save OpenRouter settings" }))

    await waitFor(() => {
      expect(apiRequestMock).toHaveBeenCalledWith(
        expect.objectContaining({
          method: "POST",
          path: "/v1/config/apply"
        })
      )
    })

    const saveCall = apiRequestMock.mock.calls.find(
      ([args]) => args.path === "/v1/config/apply"
    )
    if (!saveCall) {
      throw new Error("Expected a config apply request")
    }
    const requestBody = JSON.parse(saveCall[0].body as string)

    expect(requestBody.write_to_env_file).toBe(false)
    expect(requestBody.changes).toEqual({
      default_model: "openrouter/qwen/qwen3-32b",
      openrouter_api_key: "sk-or-test-123"
    })
    expect(screen.getByLabelText("Default model")).toHaveValue("openrouter/qwen/qwen3-32b")

    expect(
      await screen.findByText(
        "Saved 2 OpenRouter settings. Restart the backend to apply infrastructure changes."
      )
    ).toBeInTheDocument()
  })

  it("tests the OpenRouter connection with the current draft values", async () => {
    const user = userEvent.setup()

    render(<MessagingSetup token="jwt" apiKey="ops-key" />)

    await screen.findByDisplayValue("openrouter/qwen/qwen3-coder-flash")
    await user.click(screen.getByRole("button", { name: "Show advanced settings" }))
    await user.clear(screen.getByLabelText("Base URL"))
    await user.type(screen.getByLabelText("Base URL"), "https://example.com/api/v1")
    await user.clear(screen.getByLabelText("Default model"))
    await user.type(screen.getByLabelText("Default model"), "qwen/qwen3-32b")
    await user.type(screen.getByLabelText("API key"), "sk-or-probe-123")
    await user.click(screen.getByRole("button", { name: "Test connection" }))

    await waitFor(() => {
      expect(apiRequestMock).toHaveBeenCalledWith(
        expect.objectContaining({
          method: "POST",
          path: "/v1/openrouter/probe",
          token: "jwt",
          apiKey: "ops-key"
        })
      )
    })

    const probeCall = apiRequestMock.mock.calls.find(
      ([args]) => args.path === "/v1/openrouter/probe"
    )
    if (!probeCall) {
      throw new Error("Expected an OpenRouter probe request")
    }
    const probeBody = JSON.parse(probeCall[0].body as string)

    expect(probeBody.openrouter_api_key).toBe("sk-or-probe-123")
    expect(probeBody.openrouter_base_url).toBe("https://example.com/api/v1")
    expect(probeBody.default_model).toBe("openrouter/qwen/qwen3-32b")

    expect(
      await screen.findByText(
        "Connection ok Model: openrouter/qwen/qwen3-coder-flash. Latency: 321ms."
      )
    ).toBeInTheDocument()
  })

  it("filters the model catalog and applies a selected model", async () => {
    const user = userEvent.setup()

    render(<MessagingSetup />)

    await screen.findByRole("heading", { name: "Claude 3.7 Sonnet" })
    await user.type(screen.getByLabelText("Search catalog"), "claude")
    const catalog = screen.getByRole("list", {
      name: "OpenRouter model catalog results"
    })

    expect(
      within(catalog).getByRole("heading", { name: "Claude 3.7 Sonnet" })
    ).toBeInTheDocument()
    expect(within(catalog).queryByRole("heading", { name: "GPT-5.2" })).not.toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "Use model" }))

    expect(screen.getByLabelText("Default model")).toHaveValue(
      "openrouter/anthropic/claude-3.7-sonnet"
    )
  })

  it("offers known-working quick picks and warns when a catalog-only model is selected", async () => {
    const user = userEvent.setup()

    render(<MessagingSetup />)

    await screen.findByText("Known working models")
    await user.click(
      screen.getByRole("button", {
        name: "Use openrouter/qwen/qwen3-32b as default model"
      })
    )

    expect(screen.getByLabelText("Default model")).toHaveValue("openrouter/qwen/qwen3-32b")
    expect(screen.queryByText(/catalog\/manual only/)).not.toBeInTheDocument()

    await user.type(screen.getByLabelText("Search catalog"), "claude")
    await user.click(screen.getByRole("button", { name: "Use model" }))

    expect(screen.getByLabelText("Default model")).toHaveValue(
      "openrouter/anthropic/claude-3.7-sonnet"
    )
    expect(
      screen.getByText(/Catalog presence does not guarantee your account\/provider can route it/)
    ).toBeInTheDocument()
  })

  it("calls the register API and shows a success status when a token is entered and Connect is clicked", async () => {
    const user = userEvent.setup()

    render(<MessagingSetup />)

    await screen.findByText("Loaded 5 OpenRouter models.")

    const telegramInput = screen.getByPlaceholderText(/123456789/)
    await user.type(telegramInput, "my-bot-token")

    await user.click(screen.getByRole("button", { name: "Connect Telegram" }))

    await waitFor(() => {
      expect(apiRequestMock).toHaveBeenCalledWith(
        expect.objectContaining({
          method: "POST",
          path: "/v1/connectors/messaging/register"
        })
      )
    })

    const registerCall = apiRequestMock.mock.calls.find(
      ([args]: [{ path: string }]) => args.path === "/v1/connectors/messaging/register"
    )
    if (!registerCall) {
      throw new Error("Expected a messaging register request")
    }
    const requestBody = JSON.parse(registerCall[0].body as string)
    expect(requestBody.adapter).toBe("telegram")
    expect(requestBody.config.token).toBe("my-bot-token")

    expect(
      await screen.findByText("Health check status: ok")
    ).toBeInTheDocument()
  })

  it("shows a warning when Connect is clicked without entering a token", async () => {
    const user = userEvent.setup()

    render(<MessagingSetup />)

    await screen.findByText("Loaded 5 OpenRouter models.")
    await user.click(screen.getByRole("button", { name: "Connect Telegram" }))

    expect(
      await screen.findByText("Enter a Bot Token before connecting.")
    ).toBeInTheDocument()
  })
})
