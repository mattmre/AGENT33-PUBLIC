import { useEffect, useMemo, useState } from "react"

import { apiRequest } from "../../lib/api"
import {
  OPENROUTER_RECOMMENDED_MODELS,
  type OpenRouterModelEntry,
  filterOpenRouterModels,
  formatOpenRouterNumber,
  getOpenRouterRecommendedModel,
  normalizeLikelyOpenRouterModelRef,
  parseOpenRouterModels
} from "../../lib/openrouterModels"
import {
  asRecord,
  extractResultMessage,
  readNumber,
  readString
} from "../../lib/valueReaders"

interface MessagingSetupProps {
  token?: string
  apiKey?: string
}

type StatusTone = "info" | "success" | "warning" | "error"

interface StatusMessage {
  tone: StatusTone
  message: string
}

interface OpenRouterBaseline {
  defaultModel: string
  baseUrl: string
  siteUrl: string
  appName: string
  appCategory: string
}

interface OpenRouterFormState extends OpenRouterBaseline {
  apiKey: string
  writeToEnvFile: boolean
  removeStoredKey: boolean
}

interface ConfigSnapshot {
  baseline: OpenRouterBaseline
  storedKeyHint: string
  hasStoredKey: boolean
}

interface PlaceholderPlatformCard {
  icon: string
  title: string
  description: string
  label: string
  placeholder: string
  inputType: "password" | "text"
  buttonLabel: string
  configKey: string
  adapterName: string
}

const DEFAULT_OPENROUTER_BASELINE: OpenRouterBaseline = {
  defaultModel: "",
  baseUrl: "https://openrouter.ai/api/v1",
  siteUrl: "http://localhost",
  appName: "AGENT-33",
  appCategory: "cli-agent"
}

const INITIAL_OPENROUTER_FORM: OpenRouterFormState = {
  ...DEFAULT_OPENROUTER_BASELINE,
  apiKey: "",
  writeToEnvFile: true,
  removeStoredKey: false
}

const OPENROUTER_CATALOG_PREVIEW_LIMIT = 12
const OPENROUTER_MODEL_OPTION_LIMIT = 50

const PLACEHOLDER_PLATFORM_CARDS: PlaceholderPlatformCard[] = [
  {
    icon: "📱",
    title: "Telegram",
    description: "Connect via official Telegram Bot API.",
    label: "Bot Token",
    placeholder: "123456789:ABCdefGHIjklMNO...",
    inputType: "password",
    buttonLabel: "Connect Telegram",
    configKey: "token",
    adapterName: "telegram"
  },
  {
    icon: "🎮",
    title: "Discord",
    description: "Connect via Discord Developer Portal.",
    label: "Bot Token",
    placeholder: "MTAxMjM0NTY3ODkw...",
    inputType: "password",
    buttonLabel: "Connect Discord",
    configKey: "token",
    adapterName: "discord"
  },
  {
    icon: "💬",
    title: "Signal",
    description: "Requires a self-hosted signal-cli REST bridge.",
    label: "Bridge URL",
    placeholder: "http://localhost:8080",
    inputType: "text",
    buttonLabel: "Connect Signal",
    configKey: "bridge_url",
    adapterName: "signal"
  },
  {
    icon: "🍏",
    title: "iMessage",
    description: "Requires BlueBubbles or a macOS AppleScript bridge.",
    label: "Bridge Host URL",
    placeholder: "http://mac-mini.local:1234",
    inputType: "text",
    buttonLabel: "Connect iMessage",
    configKey: "bridge_url",
    adapterName: "imessage"
  }
]

function normalizeConfiguredValue(value: string, fallback: string): string {
  return value.trim() || fallback
}

function buildConfigSnapshot(data: unknown): ConfigSnapshot {
  const root = asRecord(data)
  const groups = asRecord(root.groups)
  const llm = asRecord(groups.llm)
  const ollama = asRecord(groups.ollama)

  const storedKeyHint =
    readString(llm.openrouter_api_key) || readString(llm.openrouter_api_key_redacted)

  return {
    baseline: {
      defaultModel: normalizeLikelyOpenRouterModelRef(
        readString(llm.default_model) || readString(ollama.default_model)
      ),
      baseUrl:
        readString(llm.openrouter_base_url) || DEFAULT_OPENROUTER_BASELINE.baseUrl,
      siteUrl:
        readString(llm.openrouter_site_url) || DEFAULT_OPENROUTER_BASELINE.siteUrl,
      appName:
        readString(llm.openrouter_app_name) || DEFAULT_OPENROUTER_BASELINE.appName,
      appCategory:
        readString(llm.openrouter_app_category) || DEFAULT_OPENROUTER_BASELINE.appCategory
    },
    storedKeyHint,
    hasStoredKey: storedKeyHint.trim() !== ""
  }
}

function renderStatusMessage(id: string, status: StatusMessage): JSX.Element {
  const role = status.tone === "error" ? "alert" : "status"
  const ariaLive = status.tone === "error" ? undefined : "polite"

  return (
    <div
      id={id}
      className={`integration-status integration-status--${status.tone}`}
      role={role}
      aria-live={ariaLive}
    >
      {status.message}
    </div>
  )
}

export function MessagingSetup({ token = "", apiKey = "" }: MessagingSetupProps): JSX.Element {
  const [placeholderInputs, setPlaceholderInputs] = useState<Record<string, string>>({
    Telegram: "",
    Discord: "",
    Signal: "",
    iMessage: ""
  })
  const [platformStatuses, setPlatformStatuses] = useState<Record<string, StatusMessage>>({})
  const [connectingPlatforms, setConnectingPlatforms] = useState<Record<string, boolean>>({})
  const [openRouterForm, setOpenRouterForm] = useState<OpenRouterFormState>(
    INITIAL_OPENROUTER_FORM
  )
  const [baseline, setBaseline] = useState<OpenRouterBaseline>(DEFAULT_OPENROUTER_BASELINE)
  const [setupStatus, setSetupStatus] = useState<StatusMessage>({
    tone: "info",
    message: "Loading OpenRouter settings..."
  })
  const [probeStatus, setProbeStatus] = useState<StatusMessage | null>(null)
  const [catalogStatus, setCatalogStatus] = useState<StatusMessage>({
    tone: "info",
    message: "Loading OpenRouter model catalog..."
  })
  const [storedKeyHint, setStoredKeyHint] = useState("")
  const [hasStoredKey, setHasStoredKey] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [modelSearch, setModelSearch] = useState("")
  const [isSaving, setIsSaving] = useState(false)
  const [isProbing, setIsProbing] = useState(false)
  const [catalogLoading, setCatalogLoading] = useState(true)
  const [models, setModels] = useState<OpenRouterModelEntry[]>([])

  useEffect(() => {
    let isCancelled = false

    async function loadOpenRouterData(): Promise<void> {
      const configRequest = apiRequest({
        method: "GET",
        path: "/v1/operator/config",
        token,
        apiKey
      })
      const catalogRequest = apiRequest({
        method: "GET",
        path: "/v1/openrouter/models",
        token,
        apiKey
      })

      const [configResult, catalogResult] = await Promise.allSettled([
        configRequest,
        catalogRequest
      ])

      if (isCancelled) {
        return
      }

      if (configResult.status === "fulfilled" && configResult.value.ok) {
        const snapshot = buildConfigSnapshot(configResult.value.data)
        setBaseline(snapshot.baseline)
        setOpenRouterForm((currentForm) => ({
          ...currentForm,
          ...snapshot.baseline,
          apiKey: "",
          removeStoredKey: false
        }))
        setStoredKeyHint(snapshot.storedKeyHint)
        setHasStoredKey(snapshot.hasStoredKey)
        setSetupStatus({
          tone: "success",
          message: snapshot.hasStoredKey
            ? "Loaded OpenRouter settings from the server. A stored API key is already configured."
            : "Loaded OpenRouter settings from the server."
        })
      } else {
        const fallbackMessage = "Could not load the current OpenRouter server configuration."
        const message =
          configResult.status === "fulfilled"
            ? extractResultMessage(configResult.value.data, fallbackMessage)
            : configResult.reason instanceof Error
              ? configResult.reason.message
              : fallbackMessage

        setSetupStatus({ tone: "error", message })
      }

      if (catalogResult.status === "fulfilled" && catalogResult.value.ok) {
        const parsedModels = parseOpenRouterModels(catalogResult.value.data)
        setModels(parsedModels)
        setCatalogStatus({
          tone: parsedModels.length > 0 ? "success" : "warning",
          message:
            parsedModels.length > 0
              ? `Loaded ${parsedModels.length} OpenRouter models.`
              : "The OpenRouter catalog is currently empty."
        })
      } else {
        const fallbackMessage = "Could not load the OpenRouter model catalog."
        const message =
          catalogResult.status === "fulfilled"
            ? extractResultMessage(catalogResult.value.data, fallbackMessage)
            : catalogResult.reason instanceof Error
              ? catalogResult.reason.message
              : fallbackMessage

        setCatalogStatus({ tone: "error", message })
      }

      setCatalogLoading(false)
    }

    void loadOpenRouterData()

    return () => {
      isCancelled = true
    }
  }, [apiKey, token])

  const filteredModels = useMemo(() => {
    return filterOpenRouterModels(models, modelSearch)
  }, [modelSearch, models])

  const visibleModels = filteredModels.slice(0, OPENROUTER_CATALOG_PREVIEW_LIMIT)
  const datalistModelOptions = useMemo(() => {
    const query = openRouterForm.defaultModel.trim()
    const optionSource = query ? filterOpenRouterModels(models, query) : models

    return optionSource.slice(0, OPENROUTER_MODEL_OPTION_LIMIT)
  }, [models, openRouterForm.defaultModel])
  const trimmedDefaultModel = openRouterForm.defaultModel.trim()
  const normalizedDefaultModel = normalizeLikelyOpenRouterModelRef(trimmedDefaultModel)
  const selectedRecommendedModel = useMemo(() => {
    return getOpenRouterRecommendedModel(normalizedDefaultModel)
  }, [normalizedDefaultModel])

  function handlePlaceholderInputChange(platform: string, value: string): void {
    setPlaceholderInputs((currentValues) => ({
      ...currentValues,
      [platform]: value
    }))
  }

  async function handleConnect(card: PlaceholderPlatformCard): Promise<void> {
    const inputValue = placeholderInputs[card.title] ?? ""
    if (!inputValue.trim()) {
      setPlatformStatuses((current) => ({
        ...current,
        [card.title]: { tone: "warning", message: `Enter a ${card.label} before connecting.` }
      }))
      return
    }

    setConnectingPlatforms((current) => ({ ...current, [card.title]: true }))
    setPlatformStatuses((current) => ({
      ...current,
      [card.title]: { tone: "info", message: `Connecting to ${card.title}...` }
    }))

    try {
      const response = await apiRequest({
        method: "POST",
        path: "/v1/connectors/messaging/register",
        token,
        apiKey,
        body: JSON.stringify({
          adapter: card.adapterName,
          config: { [card.configKey]: inputValue.trim() }
        })
      })

      if (response.ok) {
        const payload = response.data as { status?: string; detail?: string }
        const adapterStatus = payload.status ?? "unknown"
        const detail = payload.detail ?? ""
        const tone: StatusTone =
          adapterStatus === "ok" || adapterStatus === "connected"
            ? "success"
            : adapterStatus === "pending" || adapterStatus === "degraded"
              ? "warning"
              : "error"
        setPlatformStatuses((current) => ({
          ...current,
          [card.title]: {
            tone,
            message: detail || `${card.title} status: ${adapterStatus}`
          }
        }))
      } else {
        const payload = response.data as { detail?: string }
        setPlatformStatuses((current) => ({
          ...current,
          [card.title]: {
            tone: "error",
            message: payload.detail ?? `${card.title} connection failed.`
          }
        }))
      }
    } catch (error) {
      setPlatformStatuses((current) => ({
        ...current,
        [card.title]: {
          tone: "error",
          message:
            error instanceof Error ? error.message : `${card.title} connection failed.`
        }
      }))
    } finally {
      setConnectingPlatforms((current) => ({ ...current, [card.title]: false }))
    }
  }

  function handleOpenRouterFieldChange<K extends keyof OpenRouterFormState>(
    field: K,
    value: OpenRouterFormState[K]
  ): void {
    setOpenRouterForm((currentForm) => ({
      ...currentForm,
      [field]: value
    }))
  }

  function buildConfigChanges(): Record<string, unknown> {
    const normalizedForm = {
      defaultModel: normalizeLikelyOpenRouterModelRef(openRouterForm.defaultModel),
      baseUrl: normalizeConfiguredValue(
        openRouterForm.baseUrl,
        DEFAULT_OPENROUTER_BASELINE.baseUrl
      ),
      siteUrl: normalizeConfiguredValue(
        openRouterForm.siteUrl,
        DEFAULT_OPENROUTER_BASELINE.siteUrl
      ),
      appName: normalizeConfiguredValue(
        openRouterForm.appName,
        DEFAULT_OPENROUTER_BASELINE.appName
      ),
      appCategory: normalizeConfiguredValue(
        openRouterForm.appCategory,
        DEFAULT_OPENROUTER_BASELINE.appCategory
      )
    }

    const normalizedBaseline = {
      defaultModel: normalizeLikelyOpenRouterModelRef(baseline.defaultModel),
      baseUrl: normalizeConfiguredValue(baseline.baseUrl, DEFAULT_OPENROUTER_BASELINE.baseUrl),
      siteUrl: normalizeConfiguredValue(baseline.siteUrl, DEFAULT_OPENROUTER_BASELINE.siteUrl),
      appName: normalizeConfiguredValue(baseline.appName, DEFAULT_OPENROUTER_BASELINE.appName),
      appCategory: normalizeConfiguredValue(
        baseline.appCategory,
        DEFAULT_OPENROUTER_BASELINE.appCategory
      )
    }

    const changes: Record<string, unknown> = {}

    if (normalizedForm.defaultModel !== normalizedBaseline.defaultModel) {
      changes.default_model = normalizedForm.defaultModel
    }
    if (normalizedForm.baseUrl !== normalizedBaseline.baseUrl) {
      changes.openrouter_base_url = normalizedForm.baseUrl
    }
    if (normalizedForm.siteUrl !== normalizedBaseline.siteUrl) {
      changes.openrouter_site_url = normalizedForm.siteUrl
    }
    if (normalizedForm.appName !== normalizedBaseline.appName) {
      changes.openrouter_app_name = normalizedForm.appName
    }
    if (normalizedForm.appCategory !== normalizedBaseline.appCategory) {
      changes.openrouter_app_category = normalizedForm.appCategory
    }

    const trimmedApiKey = openRouterForm.apiKey.trim()
    if (trimmedApiKey) {
      changes.openrouter_api_key = trimmedApiKey
    } else if (openRouterForm.removeStoredKey) {
      changes.openrouter_api_key = ""
    }

    return changes
  }

  function buildProbePayload(): Record<string, unknown> {
    const payload: Record<string, unknown> = {
      openrouter_base_url: normalizeConfiguredValue(
        openRouterForm.baseUrl,
        DEFAULT_OPENROUTER_BASELINE.baseUrl
      ),
      openrouter_site_url: normalizeConfiguredValue(
        openRouterForm.siteUrl,
        DEFAULT_OPENROUTER_BASELINE.siteUrl
      ),
      openrouter_app_name: normalizeConfiguredValue(
        openRouterForm.appName,
        DEFAULT_OPENROUTER_BASELINE.appName
      ),
      openrouter_app_category: normalizeConfiguredValue(
        openRouterForm.appCategory,
        DEFAULT_OPENROUTER_BASELINE.appCategory
      )
    }

    const normalizedModel = normalizeLikelyOpenRouterModelRef(openRouterForm.defaultModel)
    if (normalizedModel) {
      payload.default_model = normalizedModel
    }

    const trimmedApiKey = openRouterForm.apiKey.trim()
    if (trimmedApiKey) {
      payload.openrouter_api_key = trimmedApiKey
    } else if (openRouterForm.removeStoredKey) {
      payload.openrouter_api_key = ""
    }

    return payload
  }

  async function handleSaveOpenRouter(): Promise<void> {
    const changes = buildConfigChanges()
    if (Object.keys(changes).length === 0) {
      setSetupStatus({
        tone: "info",
        message: "No OpenRouter changes to save yet."
      })
      return
    }

    setIsSaving(true)
    setSetupStatus({
      tone: "info",
      message: "Saving OpenRouter settings to the server..."
    })

    try {
      const response = await apiRequest({
        method: "POST",
        path: "/v1/config/apply",
        token,
        apiKey,
        body: JSON.stringify({
          changes,
          write_to_env_file: openRouterForm.writeToEnvFile
        })
      })

      const payload = asRecord(response.data)
      const applied = Array.isArray(payload.applied)
        ? payload.applied.filter((item): item is string => typeof item === "string")
        : []
      const validationErrors = Array.isArray(payload.validation_errors)
        ? payload.validation_errors.filter((item): item is string => typeof item === "string")
        : []
      const rejected = Array.isArray(payload.rejected)
        ? payload.rejected
            .filter((item): item is [string, string] => Array.isArray(item) && item.length >= 2)
            .map(([field, reason]) => `${field}: ${reason}`)
        : []

      if (!response.ok || validationErrors.length > 0 || rejected.length > 0) {
        const problemDetails = [...validationErrors, ...rejected].join(" ")
        setSetupStatus({
          tone: "error",
          message:
            problemDetails || extractResultMessage(response.data, "Could not save OpenRouter settings.")
        })
        return
      }

      const nextBaseline: OpenRouterBaseline = {
        defaultModel: normalizeLikelyOpenRouterModelRef(openRouterForm.defaultModel),
        baseUrl: normalizeConfiguredValue(
          openRouterForm.baseUrl,
          DEFAULT_OPENROUTER_BASELINE.baseUrl
        ),
        siteUrl: normalizeConfiguredValue(
          openRouterForm.siteUrl,
          DEFAULT_OPENROUTER_BASELINE.siteUrl
        ),
        appName: normalizeConfiguredValue(
          openRouterForm.appName,
          DEFAULT_OPENROUTER_BASELINE.appName
        ),
        appCategory: normalizeConfiguredValue(
          openRouterForm.appCategory,
          DEFAULT_OPENROUTER_BASELINE.appCategory
        )
      }

      setBaseline(nextBaseline)
      setOpenRouterForm((currentForm) => ({
        ...currentForm,
        apiKey: "",
        removeStoredKey: false,
        ...nextBaseline
      }))

      const newHasStoredKey = openRouterForm.removeStoredKey
        ? false
        : openRouterForm.apiKey.trim()
          ? true
          : hasStoredKey
      setHasStoredKey(newHasStoredKey)
      setStoredKeyHint(newHasStoredKey ? storedKeyHint || "configured" : "")

      const restartRequired = payload.restart_required === true
      setSetupStatus({
        tone: "success",
        message: `${applied.length > 0 ? `Saved ${applied.length} OpenRouter setting${applied.length === 1 ? "" : "s"}.` : "OpenRouter settings saved."}${restartRequired ? " Restart the backend to apply infrastructure changes." : ""}`
      })
    } catch (error) {
      setSetupStatus({
        tone: "error",
        message:
          error instanceof Error
            ? error.message
            : "Could not save OpenRouter settings."
      })
    } finally {
      setIsSaving(false)
    }
  }

  async function handleProbeOpenRouter(): Promise<void> {
    setIsProbing(true)
    setProbeStatus({
      tone: "info",
      message: "Testing the OpenRouter connection..."
    })

    try {
      const response = await apiRequest({
        method: "POST",
        path: "/v1/openrouter/probe",
        token,
        apiKey,
        body: JSON.stringify(buildProbePayload())
      })

      const payload = asRecord(response.data)
      const probeSucceeded = response.ok && payload.ok !== false && !readString(payload.error)
      const parts = [
        extractResultMessage(
          response.data,
          probeSucceeded
            ? "OpenRouter connection succeeded."
            : "OpenRouter connection failed."
        )
      ]

      const selectedModel =
        readString(payload.model) ||
        readString(payload.default_model) ||
        readString(payload.model_id)
      if (selectedModel) {
        parts.push(`Model: ${selectedModel}.`)
      }

      const latency = readNumber(payload.latency_ms) ?? readNumber(payload.duration_ms)
      if (latency !== null) {
        parts.push(`Latency: ${Math.round(latency)}ms.`)
      }

      setProbeStatus({
        tone: probeSucceeded ? "success" : "error",
        message: parts.join(" ")
      })
    } catch (error) {
      setProbeStatus({
        tone: "error",
        message:
          error instanceof Error
            ? error.message
            : "OpenRouter connection failed."
      })
    } finally {
      setIsProbing(false)
    }
  }

  return (
    <div className="messaging-setup">
      <div className="setup-header">
        <h2>Messaging Integrations</h2>
        <p>
          Connect your agent to external messaging platforms to chat from anywhere.
        </p>
      </div>

      <div className="setup-grid">
        <section className="setup-card openrouter-card" aria-labelledby="openrouter-heading">
          <div className="card-icon openrouter-icon" aria-hidden="true">
            🧠
          </div>
          <div className="openrouter-card__header">
            <div>
              <h3 id="openrouter-heading">OpenRouter</h3>
              <p>
                Store your OpenRouter credentials on the AGENT-33 server, choose a
                default model, and browse the live model catalog before you save.
              </p>
            </div>
            <div className="setup-links">
              <a
                href="https://openrouter.ai/docs/quickstart"
                target="_blank"
                rel="noreferrer"
              >
                OpenRouter docs
              </a>
              <a
                href="https://openrouter.ai/models"
                target="_blank"
                rel="noreferrer"
              >
                Model browser
              </a>
            </div>
          </div>

          {renderStatusMessage("openrouter-setup-status", setupStatus)}
          {probeStatus ? renderStatusMessage("openrouter-probe-status", probeStatus) : null}

          <div className="openrouter-form-grid">
            <label htmlFor="openrouter-api-key" className="openrouter-field">
              <span>API key</span>
              <input
                id="openrouter-api-key"
                type="password"
                value={openRouterForm.apiKey}
                onChange={(event) => {
                  handleOpenRouterFieldChange("apiKey", event.target.value)
                  if (event.target.value.trim() !== "" && openRouterForm.removeStoredKey) {
                    handleOpenRouterFieldChange("removeStoredKey", false)
                  }
                }}
                placeholder={
                  hasStoredKey
                    ? "Stored on server — enter a new key to replace it"
                    : "sk-or-v1-..."
                }
                autoComplete="new-password"
                aria-describedby="openrouter-key-help"
              />
            </label>

            <label htmlFor="openrouter-default-model" className="openrouter-field">
              <span>Default model</span>
              <input
                id="openrouter-default-model"
                type="text"
                list="openrouter-model-options"
                value={openRouterForm.defaultModel}
                onChange={(event) =>
                  handleOpenRouterFieldChange("defaultModel", event.target.value)
                }
                onBlur={(event) =>
                  handleOpenRouterFieldChange(
                    "defaultModel",
                    normalizeLikelyOpenRouterModelRef(event.target.value)
                  )
                }
                placeholder="openrouter/qwen/qwen3-coder-flash"
                aria-describedby="openrouter-model-help"
              />
            </label>
          </div>

          <datalist id="openrouter-model-options">
            {datalistModelOptions.map((model) => (
              <option key={model.id} value={model.id}>
                {model.name}
              </option>
            ))}
          </datalist>

          <div className="openrouter-inline-help" id="openrouter-key-help">
            {hasStoredKey
              ? `A server-side OpenRouter key is already configured${storedKeyHint ? ` (${storedKeyHint})` : ""}. Leave this field blank to keep it.`
              : "The real key is only sent to the AGENT-33 server when you save or test the connection."}
          </div>
          <div className="openrouter-inline-help" id="openrouter-model-help">
            Pick a known-working ref below, browse the public catalog, or type any
            OpenRouter model ID manually, such as
            <code> openrouter/qwen/qwen3-coder-flash </code>
            or
            <code> openrouter/qwen/qwen3-coder-30b-a3b-instruct</code>. Suggestions
            are limited to the first 50 catalog matches to keep this input responsive.
          </div>

          <div className="integration-status integration-status--warning openrouter-advisory">
            The public OpenRouter catalog can list models that are not enabled for this
            account or provider route yet. If a model fails at runtime, switch back to
            one of the known-working refs below.
          </div>

          <div
            className="openrouter-recommendations"
            role="group"
            aria-labelledby="openrouter-recommendations-heading"
          >
            <div className="openrouter-recommendations__header">
              <h4 id="openrouter-recommendations-heading">Known working models</h4>
              <p>Explicit OpenRouter-ready refs verified with this setup.</p>
            </div>
            <div className="openrouter-recommendation-list">
              {OPENROUTER_RECOMMENDED_MODELS.map((model) => {
                const isSelected = normalizedDefaultModel === model.id
                return (
                  <button
                    key={model.id}
                    type="button"
                    className={`openrouter-recommendation-button${isSelected ? " is-selected" : ""}`}
                    onClick={() => handleOpenRouterFieldChange("defaultModel", model.id)}
                    aria-pressed={isSelected}
                    aria-label={`Use ${model.id} as default model`}
                  >
                    <div className="openrouter-recommendation-button__top">
                      <strong className="openrouter-recommendation-button__name">
                        {model.name}
                      </strong>
                      <span className="model-pill model-pill--recommended">
                        {model.badgeLabel}
                      </span>
                    </div>
                    <span className="openrouter-model-id openrouter-recommendation-id">
                      {model.id}
                    </span>
                    <p className="openrouter-recommendation-button__description">
                      {model.description}
                    </p>
                  </button>
                )
              })}
            </div>
          </div>

          {trimmedDefaultModel && !selectedRecommendedModel ? (
            <div className="integration-status integration-status--warning openrouter-selection-warning">
              This selection is still catalog/manual only. Catalog presence does not
              guarantee your account/provider can route it. If probe or chat fails,
              switch to openrouter/qwen/qwen3-coder-flash or another known-working pick
              above.
            </div>
          ) : null}

          {hasStoredKey ? (
            <label className="setup-checkbox">
              <input
                type="checkbox"
                checked={openRouterForm.removeStoredKey}
                onChange={(event) =>
                  handleOpenRouterFieldChange("removeStoredKey", event.target.checked)
                }
                disabled={openRouterForm.apiKey.trim() !== ""}
              />
              <span>Remove the stored server key on save</span>
            </label>
          ) : null}

          <button
            type="button"
            className={`advanced-toggle-btn${showAdvanced ? " active" : ""}`}
            onClick={() => setShowAdvanced((currentValue) => !currentValue)}
            aria-expanded={showAdvanced}
            aria-controls="openrouter-advanced-settings"
          >
            {showAdvanced ? "Hide advanced settings" : "Show advanced settings"}
          </button>

          {showAdvanced ? (
            <div id="openrouter-advanced-settings" className="openrouter-advanced-grid">
              <label htmlFor="openrouter-base-url" className="openrouter-field">
                <span>Base URL</span>
                <input
                  id="openrouter-base-url"
                  type="text"
                  value={openRouterForm.baseUrl}
                  onChange={(event) =>
                    handleOpenRouterFieldChange("baseUrl", event.target.value)
                  }
                />
              </label>
              <label htmlFor="openrouter-site-url" className="openrouter-field">
                <span>Site URL</span>
                <input
                  id="openrouter-site-url"
                  type="text"
                  value={openRouterForm.siteUrl}
                  onChange={(event) =>
                    handleOpenRouterFieldChange("siteUrl", event.target.value)
                  }
                />
              </label>
              <label htmlFor="openrouter-app-name" className="openrouter-field">
                <span>App name</span>
                <input
                  id="openrouter-app-name"
                  type="text"
                  value={openRouterForm.appName}
                  onChange={(event) =>
                    handleOpenRouterFieldChange("appName", event.target.value)
                  }
                />
              </label>
              <label htmlFor="openrouter-app-category" className="openrouter-field">
                <span>App category</span>
                <input
                  id="openrouter-app-category"
                  type="text"
                  value={openRouterForm.appCategory}
                  onChange={(event) =>
                    handleOpenRouterFieldChange("appCategory", event.target.value)
                  }
                />
              </label>
            </div>
          ) : null}

          <label className="setup-checkbox">
            <input
              type="checkbox"
              checked={openRouterForm.writeToEnvFile}
              onChange={(event) =>
                handleOpenRouterFieldChange("writeToEnvFile", event.target.checked)
              }
            />
            <span>Persist these settings to the server .env file for restarts</span>
          </label>

          <div className="setup-actions">
            <button type="button" onClick={() => void handleSaveOpenRouter()} disabled={isSaving}>
              {isSaving ? "Saving..." : "Save OpenRouter settings"}
            </button>
            <button
              type="button"
              className="setup-button-secondary"
              onClick={() => void handleProbeOpenRouter()}
              disabled={isProbing}
            >
              {isProbing ? "Testing..." : "Test connection"}
            </button>
          </div>

          <div className="openrouter-catalog-section">
            <div className="openrouter-catalog-header">
              <div>
                <h4>Model catalog</h4>
                <p>
                  Search the live catalog, compare pricing and context windows, then use a
                  model as your default with one click. Catalog presence still does not
                  guarantee account/provider availability.
                </p>
              </div>
              <label htmlFor="openrouter-model-search" className="openrouter-search-field">
                <span>Search catalog</span>
                <input
                  id="openrouter-model-search"
                  type="search"
                  value={modelSearch}
                  onChange={(event) => setModelSearch(event.target.value)}
                  placeholder="Search models, providers, or capabilities"
                />
              </label>
            </div>

            {renderStatusMessage("openrouter-catalog-status", catalogStatus)}

            <p className="openrouter-catalog-count">
              {catalogLoading
                ? "Loading models..."
                : `${filteredModels.length} of ${models.length} model${models.length === 1 ? "" : "s"} match${filteredModels.length === 1 ? "es" : ""} your search. Catalog-listed models can still be unavailable for this account/provider.`}
            </p>

            {visibleModels.length > 0 ? (
              <ul className="openrouter-model-list" aria-label="OpenRouter model catalog results">
                {visibleModels.map((model) => {
                  const recommendedModel = getOpenRouterRecommendedModel(model.id)
                  return (
                    <li key={model.id} className="openrouter-model-item">
                      <div className="openrouter-model-item__top">
                        <div>
                          <h5>{model.name}</h5>
                          <p className="openrouter-model-id">{model.id}</p>
                        </div>
                        <button
                          type="button"
                          className="setup-button-secondary"
                          onClick={() => handleOpenRouterFieldChange("defaultModel", model.id)}
                        >
                          Use model
                        </button>
                      </div>

                      {model.description ? <p>{model.description}</p> : null}

                      <div className="openrouter-model-metadata">
                        {recommendedModel ? (
                          <span className="model-pill model-pill--recommended">
                            {recommendedModel.badgeLabel}
                          </span>
                        ) : null}
                        {model.contextLength !== null ? (
                          <span className="model-pill">
                            Context {formatOpenRouterNumber(model.contextLength)}
                          </span>
                        ) : null}
                        {model.maxCompletionTokens !== null ? (
                          <span className="model-pill">
                            Max output {formatOpenRouterNumber(model.maxCompletionTokens)}
                          </span>
                        ) : null}
                        {model.promptPrice ? (
                          <span className="model-pill">Prompt {model.promptPrice}</span>
                        ) : null}
                        {model.completionPrice ? (
                          <span className="model-pill">
                            Completion {model.completionPrice}
                          </span>
                        ) : null}
                        {model.requestPrice ? (
                          <span className="model-pill">Request {model.requestPrice}</span>
                        ) : null}
                        {model.imagePrice ? (
                          <span className="model-pill">Image {model.imagePrice}</span>
                        ) : null}
                      </div>

                      {model.capabilities.length > 0 ? (
                        <div className="openrouter-model-capabilities">
                          {model.capabilities.map((capability) => (
                            <span key={capability} className="model-capability-pill">
                              {capability}
                            </span>
                          ))}
                        </div>
                      ) : null}
                    </li>
                  )
                })}
              </ul>
            ) : (
              <div className="openrouter-empty-state" role="status" aria-live="polite">
                No OpenRouter models match your current search.
              </div>
            )}
          </div>
        </section>

        {PLACEHOLDER_PLATFORM_CARDS.map((card) => {
          const cardStatus = platformStatuses[card.title]
          const isConnecting = connectingPlatforms[card.title] === true
          return (
            <div key={card.title} className="setup-card">
              <div className="card-icon" aria-hidden="true">
                {card.icon}
              </div>
              <h3>{card.title}</h3>
              <p>{card.description}</p>
              <label>
                {card.label}
                <input
                  type={card.inputType}
                  placeholder={card.placeholder}
                  value={placeholderInputs[card.title] ?? ""}
                  onChange={(event) =>
                    handlePlaceholderInputChange(card.title, event.target.value)
                  }
                />
              </label>
              {cardStatus
                ? renderStatusMessage(`${card.adapterName}-connect-status`, cardStatus)
                : null}
              <button
                type="button"
                onClick={() => void handleConnect(card)}
                disabled={isConnecting}
              >
                {isConnecting ? "Connecting..." : card.buttonLabel}
              </button>
            </div>
          )
        })}
      </div>
    </div>
  )
}
